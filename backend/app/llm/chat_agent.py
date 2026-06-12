import json

from ..config import CHAT_MAX_TOKENS, CHAT_MAX_TOOL_ROUNDS, MODEL
from ..db import get_conn, now
from .tools import TOOLS, execute_tool

SYSTEM_PROMPT = """You are Onboarder, an interactive guide to a codebase workspace. \
Your users are developers being onboarded and non-technical teammates (managers, QA, PMs).

You handle two kinds of requests:

1. UNDERSTANDING — "how does order placing work?". Locate the flow with tools \
(query_graph, trace_paths), read the key hops, then explain business meaning first, \
mechanics second. Call focus_view with mode "trace" so the user sees the flow.

2. INVESTIGATION — "X is slow", "there's a bug in listings", "opening one takes 10 seconds". \
Work like a senior engineer doing a first diagnosis:
   a. Find the entry points matching the report: query_graph(kind="entry_point", \
name_contains=...) — try several spellings; fall back to search_code if naming differs.
   b. trace_paths from each matching endpoint, then read_source on EVERY hop that could \
matter: handler, services, repositories, raw queries, outbound calls. Several short reads \
beat one big one.
   c. In the code you actually read, look for concrete suspects: queries or HTTP calls inside \
loops (N+1), missing pagination/LIMIT on list endpoints, sequential outbound calls that could \
be parallel or cached, heavy work inside transactions, unbounded SELECTs or large joins, \
repeated identical reads, blocking calls, missing indexes implied by WHERE clauses.
   d. Answer with a ranked "places to look" list: each item = file:line, the [node:<id>] it \
belongs to, and one sentence on why it is suspicious. Call focus_view to highlight the suspect \
path. Be explicit about what you could NOT verify from the code (e.g. DB indexes, payload \
sizes, infra) so the user knows where profiling is still needed.

Rules:
- Ground every claim in tool results. Never describe code you have not read via tools.
- Cite the graph nodes you talk about by id, inline, in the form [node:<id>] right after the claim.
- Whenever your answer discusses specific nodes or a flow, call focus_view so the user's graph \
shows what you are describing (mode "trace" for flows, "highlight" for sets, "isolate" to focus).
- Prefer plain language; explain business meaning first, mechanics second.
- If the graph lacks the answer, say so and state what evidence you would need.
- Keep answers concise; the graph carries the detail."""


def _workspace_overview(workspace_id: str) -> str:
    conn = get_conn()
    try:
        projects = conn.execute(
            "SELECT id, name, stack, status FROM projects WHERE workspace_id = ? ORDER BY id",
            (workspace_id,)).fetchall()
        counts = conn.execute(
            "SELECT project_id, kind, COUNT(*) AS n FROM nodes WHERE workspace_id = ?"
            " GROUP BY project_id, kind ORDER BY project_id, kind",
            (workspace_id,)).fetchall()
        endpoints = conn.execute(
            "SELECT name FROM nodes WHERE workspace_id = ? AND kind = 'entry_point'"
            " ORDER BY name LIMIT 30",
            (workspace_id,)).fetchall()
    finally:
        conn.close()
    lines = ["Workspace inventory:"]
    for p in projects:
        kinds = ", ".join(f"{c['kind']}={c['n']}" for c in counts if c["project_id"] == p["id"])
        lines.append(f"- project {p['id']} \"{p['name']}\" stack={p['stack']} status={p['status']} ({kinds})")
    if endpoints:
        lines.append("Sample entry points: " + "; ".join(e["name"] for e in endpoints))
    return "\n".join(lines)


def _load_history(workspace_id: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT role, content FROM chat_messages WHERE workspace_id = ?"
            " ORDER BY id DESC LIMIT ?", (workspace_id, limit)).fetchall()
    finally:
        conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _save_message(workspace_id: str, role: str, content: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_messages(workspace_id, role, content, created_at) VALUES(?,?,?,?)",
            (workspace_id, role, content, now()))
        conn.commit()
    finally:
        conn.close()


def stream_chat(workspace_id: str, user_message: str):
    """Yield (event, data) tuples: text_delta, tool_started, ui_directive, done, error."""
    from . import get_client

    client = get_client()
    system = [{
        "type": "text",
        "text": SYSTEM_PROMPT + "\n\n" + _workspace_overview(workspace_id),
        "cache_control": {"type": "ephemeral"},
    }]
    messages = _load_history(workspace_id) + [{"role": "user", "content": user_message}]
    _save_message(workspace_id, "user", user_message)

    answer_parts: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        for _round in range(CHAT_MAX_TOOL_ROUNDS):
            with client.messages.stream(
                model=MODEL,
                max_tokens=CHAT_MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=system,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        answer_parts.append(event.delta.text)
                        yield "text_delta", {"text": event.delta.text}
                final = stream.get_final_message()
            usage["input_tokens"] += final.usage.input_tokens
            usage["output_tokens"] += final.usage.output_tokens
            messages.append({"role": "assistant", "content": final.content})
            if final.stop_reason != "tool_use":
                break
            tool_results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                yield "tool_started", {"name": block.name, "input": block.input}
                if block.name == "focus_view":
                    yield "ui_directive", block.input
                    output = "ok"
                else:
                    output = execute_tool(workspace_id, block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
            messages.append({"role": "user", "content": tool_results})
    except Exception as e:
        yield "error", {"message": str(e)}
        return
    answer = "".join(answer_parts)
    if answer:
        _save_message(workspace_id, "assistant", answer)
    yield "done", {"usage": usage}


def sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
