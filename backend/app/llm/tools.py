import json
import re

from ..analysis import graph
from ..analysis.languages import iter_source_files
from ..config import resolve_root
from ..db import get_conn, row_to_dict

TOOLS = [
    {
        "name": "list_projects",
        "description": "List every project in this workspace with its stack, status and stats.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_graph",
        "description": (
            "Find nodes in the code graph. Kinds: entry_point (API endpoints/screens), "
            "logic (controllers/services), data_access (repositories), table (DB tables), "
            "outbound_call (HTTP calls to other systems), queue, external_api."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "name_contains": {"type": "string"},
                "project_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_node",
        "description": "Get full details for one node: metadata, incoming/outgoing edges with evidence, and its business-logic card if available.",
        "input_schema": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
    },
    {
        "name": "trace_paths",
        "description": "Walk the graph from a node downstream (endpoint -> ... -> table). Optionally constrain to paths reaching to_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_id": {"type": "string"},
                "to_id": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            "required": ["from_id"],
        },
    },
    {
        "name": "read_source",
        "description": "Read source lines from a project file (1-based, inclusive). Use the file/line from node evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "file": {"type": "string"},
                "start": {"type": "integer"},
                "end": {"type": "integer"},
            },
            "required": ["project_id", "file"],
        },
    },
    {
        "name": "search_code",
        "description": "Regex search across project source files. Returns file, line and matching text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "project_id": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_diff",
        "description": (
            "Compare the current graph against a saved baseline snapshot. Returns added/removed/"
            "changed nodes and added/removed edges. base: 'latest' (most recent snapshot), a "
            "snapshot label like 'baseline' or 'master', or a snapshot id. Use this when the user "
            "asks what changed, or to verify an expected change actually happened."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"base": {"type": "string"}},
        },
    },
    {
        "name": "focus_view",
        "description": (
            "Drive the user's graph visualization. Call this whenever your answer discusses specific "
            "nodes so the user sees them: mode 'highlight' lights them up, 'isolate' hides everything else, "
            "'trace' shows the path through the listed nodes in order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_ids": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["highlight", "isolate", "trace"]},
            },
            "required": ["node_ids", "mode"],
        },
    },
]


def _src_root(project_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT root_path FROM projects WHERE id = ?", (project_id,)).fetchone()
    finally:
        conn.close()
    return resolve_root(row["root_path"]) if row else None


def _list_projects(workspace_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, stack, status, stats FROM projects WHERE workspace_id = ?",
            (workspace_id,)).fetchall()
        return [row_to_dict(r, ("stats",)) for r in rows]
    finally:
        conn.close()


def _query_graph(workspace_id: str, kind=None, name_contains=None, project_id=None, limit=25) -> list[dict]:
    sql = ("SELECT id, project_id, kind, name, qualified_name, file, line_start, confidence "
           "FROM nodes WHERE workspace_id = ?")
    params: list = [workspace_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if name_contains:
        sql += " AND (name LIKE ? OR qualified_name LIKE ?)"
        params.extend([f"%{name_contains}%", f"%{name_contains}%"])
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    sql += " ORDER BY kind, name LIMIT ?"
    params.append(min(int(limit or 25), 100))
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _read_source(project_id: str, file: str, start: int | None, end: int | None) -> dict:
    root = _src_root(project_id)
    if root is None:
        return {"error": "unknown project"}
    target = (root / file).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        return {"error": "file not found"}
    lines = target.read_text("utf-8", errors="replace").splitlines()
    start = max(1, int(start or 1))
    end = min(len(lines), int(end or start + 120), start + 200)
    body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
    return {"file": file, "start": start, "end": end, "content": body}


def _search_code(workspace_id: str, pattern: str, project_id=None) -> list[dict]:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return [{"error": f"bad regex: {e}"}]
    projects = [p for p in _list_projects(workspace_id)
                if project_id is None or p["id"] == project_id]
    hits: list[dict] = []
    for p in projects:
        root = _src_root(p["id"])
        if root is None or not root.exists():
            continue
        scanned = 0
        for abs_path, rel, _lang in iter_source_files(root):
            scanned += 1
            if scanned > 5000 or len(hits) >= 50:
                break
            try:
                if abs_path.stat().st_size > 1024 * 1024:
                    continue
                for i, line in enumerate(abs_path.read_text("utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append({"project_id": p["id"], "file": rel, "line": i,
                                     "text": line.strip()[:200]})
                        if len(hits) >= 50:
                            break
            except OSError:
                continue
    return hits


def execute_tool(workspace_id: str, name: str, tool_input: dict) -> str:
    tool_input = tool_input or {}
    try:
        if name == "list_projects":
            result = _list_projects(workspace_id)
        elif name == "query_graph":
            result = _query_graph(
                workspace_id,
                kind=tool_input.get("kind"),
                name_contains=tool_input.get("name_contains"),
                project_id=tool_input.get("project_id"),
                limit=tool_input.get("limit") or 25,
            )
        elif name == "get_node":
            result = graph.node_detail(workspace_id, tool_input.get("node_id", "")) or {"error": "node not found"}
        elif name == "trace_paths":
            result = graph.trace(
                workspace_id,
                tool_input.get("from_id", ""),
                tool_input.get("to_id"),
                int(tool_input.get("max_depth") or 10),
            )
        elif name == "read_source":
            result = _read_source(
                tool_input.get("project_id", ""), tool_input.get("file", ""),
                tool_input.get("start"), tool_input.get("end"),
            )
        elif name == "search_code":
            result = _search_code(workspace_id, tool_input.get("pattern", ""), tool_input.get("project_id"))
        elif name == "get_diff":
            from ..analysis.snapshots import compute_diff
            d = compute_diff(workspace_id, tool_input.get("base") or "latest", "current")
            result = {
                "base": d["base"], "total_changes": d["total_changes"], "stats": d["stats"],
                "added_nodes": [{"id": n["id"], "kind": n["kind"], "name": n["name"]}
                                for n in d["added_nodes"][:40]],
                "removed_nodes": [{"id": n["id"], "kind": n["kind"], "name": n["name"]}
                                  for n in d["removed_nodes"][:40]],
                "changed_nodes": [{"id": c["node"]["id"], "name": c["node"]["name"],
                                   "changes": c["changes"]} for c in d["changed_nodes"][:40]],
                "added_edges": [f"{e['src']} -{e['kind']}-> {e['dst']}" for e in d["added_edges"][:40]],
                "removed_edges": [f"{e['src']} -{e['kind']}-> {e['dst']}" for e in d["removed_edges"][:40]],
            }
        elif name == "focus_view":
            result = "ok"
        else:
            result = {"error": f"unknown tool {name}"}
    except Exception as e:
        result = {"error": str(e)}
    return json.dumps(result, default=str)
