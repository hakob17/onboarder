"""Ticket → fix agent. Given a normalized Jira/ADO ticket, it investigates the
code graph with the same tools the chat agent uses, then submits a structured,
evidence-grounded proposal via the terminal `propose_fix` tool — including a
ready-to-paste implementation prompt for a coding agent. No code is written."""
import json

from ..config import CHAT_MAX_TOKENS, CHAT_MAX_TOOL_ROUNDS, MODEL
from ..db import get_conn, now
from .chat_agent import _workspace_overview
from .tools import TOOLS, execute_tool

SYSTEM_PROMPT = """You are Onboarder's fix advisor. You are given a real bug/feature \
ticket and a statically-analyzed code graph of the workspace. Your job is to find \
exactly where and how to fix it, grounded only in code you actually read.

Work like a senior engineer triaging the ticket:
1. Restate the ticket in terms of THIS system (not generic advice).
2. Locate the responsible code: query_graph / search_code to find the entry points and \
units the ticket is about (try several spellings), then trace_paths and read_source on \
EVERY hop that could matter. Several short reads beat one big one.
3. Form a root-cause hypothesis tied to specific file:line locations you read.
4. Decide the concrete change, consistent with the conventions visible in the surrounding code.
5. Call focus_view (mode "trace" or "highlight") so the user sees the implicated code on the map.

Then, and only after you have read the code you will cite, call propose_fix exactly once with:
- problem: 1-3 sentences mapping the ticket onto the real system.
- root_cause: the specific locations responsible — each with the file and line you actually \
read, and the [node:<id>] it belongs to when known.
- proposed_fix: the change to make, in plain language, justified by the code you read. No diff.
- implementation_prompt: a COMPLETE, self-contained instruction a coding agent can execute \
without this conversation. Name the exact files and functions to change with their current \
file:line, describe the precise edit, tell it to preserve existing conventions and add/adjust \
tests, and include acceptance criteria derived from the ticket. Do NOT include a diff yourself.
- risks: side effects and anything you could NOT verify from the code (tests, DB indexes, \
infra, payloads) so the human knows what still needs checking.
- confidence: high / medium / low.

Rules: never describe code you have not read via tools. If the graph genuinely lacks the \
answer, still call propose_fix with low confidence, an honest problem statement, and an \
implementation_prompt that tells the engineer what to investigate first."""

PROPOSE_FIX_TOOL = {
    "name": "propose_fix",
    "description": "Submit the final, evidence-grounded fix proposal. Call this exactly once, "
                   "at the END, after investigating with the other tools and reading the code you cite.",
    "input_schema": {
        "type": "object",
        "properties": {
            "problem": {"type": "string"},
            "root_cause": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "node_id": {"type": "string"},
                    },
                    "required": ["summary", "file"],
                },
            },
            "proposed_fix": {"type": "string"},
            "implementation_prompt": {"type": "string"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "focus_node_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["problem", "root_cause", "proposed_fix", "implementation_prompt", "risks", "confidence"],
    },
}

FIX_TOOLS = TOOLS + [PROPOSE_FIX_TOOL]


def _save(workspace_id: str, role: str, content: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_messages(workspace_id, role, content, created_at) VALUES(?,?,?,?)",
            (workspace_id, role, content, now()))
        conn.commit()
    finally:
        conn.close()


def stream_fix(workspace_id: str, ticket: dict, ticket_prompt: str):
    """Yield (event, data): text_delta, tool_started, ui_directive, fix_proposal, done, error."""
    from . import get_client

    client = get_client()
    system = [{
        "type": "text",
        "text": SYSTEM_PROMPT + "\n\n" + _workspace_overview(workspace_id),
        "cache_control": {"type": "ephemeral"},
    }]
    messages = [{"role": "user", "content": ticket_prompt}]
    label = f"{ticket.get('source', '').upper()} {ticket.get('key', '')}: {ticket.get('title', '')}"
    _save(workspace_id, "user", f"Analyze ticket — {label}")

    usage = {"input_tokens": 0, "output_tokens": 0}
    proposal: dict | None = None
    try:
        for _round in range(CHAT_MAX_TOOL_ROUNDS):
            with client.messages.stream(
                model=MODEL,
                max_tokens=CHAT_MAX_TOKENS,
                thinking={"type": "adaptive"},
                system=system,
                tools=FIX_TOOLS,
                messages=messages,
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield "text_delta", {"text": event.delta.text}
                final = stream.get_final_message()
            usage["input_tokens"] += final.usage.input_tokens
            usage["output_tokens"] += final.usage.output_tokens
            messages.append({"role": "assistant", "content": final.content})
            if final.stop_reason != "tool_use":
                break

            tool_results = []
            stop = False
            for block in final.content:
                if block.type != "tool_use":
                    continue
                if block.name == "propose_fix":
                    proposal = block.input
                    if proposal.get("focus_node_ids"):
                        yield "ui_directive", {"mode": "highlight", "node_ids": proposal["focus_node_ids"]}
                    yield "fix_proposal", proposal
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "ok"})
                    stop = True
                    continue
                yield "tool_started", {"name": block.name, "input": block.input}
                if block.name == "focus_view":
                    yield "ui_directive", block.input
                    output = "ok"
                else:
                    output = execute_tool(workspace_id, block.name, block.input)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            if stop:
                break
            messages.append({"role": "user", "content": tool_results})
    except Exception as e:
        yield "error", {"message": str(e)}
        return

    if proposal is not None:
        _save(workspace_id, "assistant", f"Fix proposal for {label}:\n{proposal.get('proposed_fix', '')}")
    yield "done", {"usage": usage, "had_proposal": proposal is not None}


def sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
