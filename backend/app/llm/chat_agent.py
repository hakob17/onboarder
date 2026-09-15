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


_CLI_ONBOARDER_TOOLS = (
    "onboarder_overview", "onboarder_list_projects", "onboarder_find_nodes",
    "onboarder_get_node", "onboarder_trace_flow", "onboarder_read_source",
    "onboarder_search_code", "onboarder_list_workspaces",
)
_CLI_TOOL_LABEL = {
    "onboarder_overview": "Read overview", "onboarder_find_nodes": "Queried graph",
    "onboarder_get_node": "Read node", "onboarder_trace_flow": "Traced paths",
    "onboarder_read_source": "Read source", "onboarder_search_code": "Searched code",
    "onboarder_list_projects": "Listed projects", "onboarder_list_workspaces": "Listed workspaces",
}


def _onboarder_mcp_command() -> tuple[str, list[str]]:
    """(command, args) to launch the Onboarder MCP server as a `claude` subprocess."""
    import sys
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp"]              # the bundled engine binary
    return sys.executable, ["-m", "app.mcp_server"]   # dev: python -m


def _stream_chat_cli(workspace_id: str, user_message: str):
    """Chat via the local `claude` CLI with full graph tool-use: claude connects to the
    Onboarder MCP server (pinned to this workspace) and calls onboarder_* tools, no key."""
    import json as _json
    import os
    import subprocess
    import tempfile

    from ..config import DATA_DIR, claude_cli_path
    _save_message(workspace_id, "user", user_message)

    exe = claude_cli_path()
    if not exe:
        yield "error", {"message": "claude CLI not found — install it or use the Anthropic key provider"}
        return

    cmd, args = _onboarder_mcp_command()
    mcp_cfg = {"mcpServers": {"onboarder": {
        "command": cmd, "args": args,
        "env": {"ONBOARDER_DATA_DIR": str(DATA_DIR), "ONBOARDER_WORKSPACE_ID": workspace_id},
    }}}
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    _json.dump(mcp_cfg, tmp)
    tmp.close()

    prompt = (f"{SYSTEM_PROMPT}\n\nUse the onboarder_* tools to ground every claim in this "
              f"workspace's real code (cite file:line). Question: {user_message}")
    allowed = ",".join(f"mcp__onboarder__{t}" for t in _CLI_ONBOARDER_TOOLS)
    argv = [exe, "-p", prompt, "--mcp-config", tmp.name, "--allowedTools", allowed,
            "--output-format", "stream-json", "--verbose"]

    answer_parts: list[str] = []
    try:
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
            env={**os.environ, "ONBOARDER_DATA_DIR": str(DATA_DIR)},
        )
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                if ev.get("is_api_error_message") or ev.get("error"):
                    continue  # handled by the result event below
                for b in ev.get("message", {}).get("content", []):
                    if b.get("type") == "text" and b.get("text"):
                        answer_parts.append(b["text"])
                        yield "text_delta", {"text": b["text"]}
                    elif b.get("type") == "tool_use":
                        short = str(b.get("name", "")).split("__")[-1]
                        yield "tool_started", {"name": _CLI_TOOL_LABEL.get(short, short), "input": b.get("input", {})}
            elif ev.get("type") == "result":
                if ev.get("is_error"):
                    yield "error", {"message": f"claude CLI: {ev.get('result') or 'error'}"}
                elif not answer_parts and ev.get("result"):
                    answer_parts.append(ev["result"])
                    yield "text_delta", {"text": ev["result"]}
        proc.wait(timeout=300)
        if proc.returncode not in (0, None) and not answer_parts:
            yield "error", {"message": f"claude CLI failed ({proc.returncode}): {(proc.stderr.read() or '')[:300]}"}
    except Exception as e:
        yield "error", {"message": str(e)}
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    answer = "".join(answer_parts)
    if answer:
        _save_message(workspace_id, "assistant", answer)
    yield "done", {"usage": {}}


def stream_chat(workspace_id: str, user_message: str):
    """Yield (event, data) tuples: text_delta, tool_started, ui_directive, done, error."""
    from ..config import ai_provider
    if ai_provider() == "claude-cli":
        yield from _stream_chat_cli(workspace_id, user_message)
        return

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
