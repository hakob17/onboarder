"""Onboarder as an MCP server.

Exposes the code-graph grounding tools over the Model Context Protocol so the AI
tools *inside* an IDE (JetBrains AI Assistant via its MCP client, Claude Code,
Cursor, …) can reason about the real architecture: find endpoints, trace a flow
endpoint → service → repository → table, read the exact source behind a node, and
search code — every answer anchored to `file:line` from the analyzed graph.

This server does NOT call an LLM itself — the IDE's assistant does the thinking;
Onboarder supplies architecture-aware, evidence-backed context. So it needs no
Anthropic key and only reads the local SQLite the engine already produced.

Transport: stdio (what IDE MCP clients spawn). Run via the bundled engine:
    onboarder-engine --mcp
with ONBOARDER_DATA_DIR pointing at the engine's data dir and, optionally,
ONBOARDER_WORKSPACE_ID pinning which analyzed workspace to serve.
"""
import json
import os

from mcp.server.mcpserver import MCPServer

from .db import get_conn
from .llm.chat_agent import _workspace_overview
from .llm.tools import _list_projects, execute_tool

mcp = MCPServer(
    "onboarder",
    instructions=(
        "Onboarder exposes a statically-analyzed map of the code in the open workspace. "
        "Use it to ground answers about how the system works in real code: call "
        "onboarder_overview first to see projects and endpoints, onboarder_find_nodes / "
        "onboarder_search_code to locate the relevant units, onboarder_trace_flow to follow "
        "a request from an endpoint down to the database, onboarder_get_node for a node's "
        "edges and evidence, and onboarder_read_source to read the exact lines. Every node "
        "and edge carries file:line evidence — cite it. Prefer these tools over guessing."
    ),
)


def _resolve_ws(explicit: str | None = None) -> str:
    """Which analyzed workspace to serve: explicit arg > env > the newest one with nodes."""
    if explicit:
        return explicit
    env = os.environ.get("ONBOARDER_WORKSPACE_ID")
    if env:
        return env
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT w.id FROM workspaces w "
            "JOIN nodes n ON n.workspace_id = w.id "
            "GROUP BY w.id ORDER BY w.created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("no analyzed workspace found — open and map a project in Onboarder first")
    return row["id"]


def _tool(name: str, ws: str | None, **params) -> str:
    return execute_tool(_resolve_ws(ws), name, params)


@mcp.tool()
def onboarder_list_workspaces() -> str:
    """List analyzed workspaces (id, name) — only needed if more than one is present."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT w.id, w.name, COUNT(n.id) AS nodes FROM workspaces w "
            "LEFT JOIN nodes n ON n.workspace_id = w.id GROUP BY w.id ORDER BY w.created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return json.dumps([dict(r) for r in rows])


@mcp.tool()
def onboarder_overview(workspace_id: str | None = None) -> str:
    """Inventory of the workspace: projects, per-kind node counts, and sample endpoints. Start here."""
    return _workspace_overview(_resolve_ws(workspace_id))


@mcp.tool()
def onboarder_list_projects(workspace_id: str | None = None) -> str:
    """Every project in the workspace with its stack, status and stats."""
    return json.dumps(_list_projects(_resolve_ws(workspace_id)), default=str)


@mcp.tool()
def onboarder_find_nodes(kind: str | None = None, name_contains: str | None = None,
                         project_id: str | None = None, limit: int = 25,
                         workspace_id: str | None = None) -> str:
    """Find nodes in the code graph. kind: entry_point (API endpoints), logic (controllers/
    services), data_access (repositories), table (DB tables), outbound_call, queue, external_api."""
    return _tool("query_graph", workspace_id, kind=kind, name_contains=name_contains,
                 project_id=project_id, limit=limit)


@mcp.tool()
def onboarder_get_node(node_id: str, workspace_id: str | None = None) -> str:
    """Full details for one node: metadata, incoming/outgoing edges with file:line evidence,
    and its business-logic summary card if one has been generated."""
    return _tool("get_node", workspace_id, node_id=node_id)


@mcp.tool()
def onboarder_trace_flow(from_id: str, to_id: str | None = None, max_depth: int = 10,
                         workspace_id: str | None = None) -> str:
    """Walk the graph downstream from a node (endpoint → service → repository → table).
    Optionally constrain to paths that reach to_id."""
    return _tool("trace_paths", workspace_id, from_id=from_id, to_id=to_id, max_depth=max_depth)


@mcp.tool()
def onboarder_read_source(project_id: str, file: str, start: int | None = None,
                          end: int | None = None) -> str:
    """Read source lines from a project file (1-based, inclusive). Use the file/line from a
    node's evidence. project_id comes from onboarder_list_projects or a node."""
    return execute_tool("", "read_source", {"project_id": project_id, "file": file,
                                             "start": start, "end": end})


@mcp.tool()
def onboarder_search_code(pattern: str, project_id: str | None = None,
                          workspace_id: str | None = None) -> str:
    """Regex search across the workspace's source files. Returns project_id, file, line and text."""
    return _tool("search_code", workspace_id, pattern=pattern, project_id=project_id)


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
