import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..analysis import graph
from ..config import llm_enabled
from ..db import get_conn, row_to_dict
from ..llm.tools import _read_source

router = APIRouter(tags=["graph"])


@router.get("/workspaces/{ws_id}/graph")
def get_graph(ws_id: str, project_id: str | None = None) -> dict:
    return graph.fetch_graph(ws_id, project_id)


@router.post("/workspaces/{ws_id}/link")
def run_linker(ws_id: str) -> dict:
    from ..analysis.linker import link_workspace
    return link_workspace(ws_id)


@router.get("/workspaces/{ws_id}/trace")
def get_trace(ws_id: str, from_id: str, to_id: str | None = None, max_depth: int = 10) -> dict:
    return {"paths": graph.trace(ws_id, from_id, to_id, min(max_depth, 15))}


@router.get("/workspaces/{ws_id}/source")
def get_source(ws_id: str, project_id: str, file: str, start: int | None = None,
               end: int | None = None) -> dict:
    result = _read_source(project_id, file, start, end)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/workspaces/{ws_id}/nodes/{node_id:path}/enrich")
def enrich(ws_id: str, node_id: str) -> dict:
    if not llm_enabled():
        raise HTTPException(503, "LLM features disabled: set ANTHROPIC_API_KEY")
    from ..llm.enrich import enrich_node
    try:
        return {"node_id": node_id, "card": enrich_node(ws_id, node_id)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/workspaces/{ws_id}/nodes/{node_id:path}")
def get_node(ws_id: str, node_id: str) -> dict:
    detail = graph.node_detail(ws_id, node_id)
    if detail is None:
        raise HTTPException(404, "node not found")
    return detail


class LinkUpdate(BaseModel):
    status: str  # confirmed | rejected | inferred


@router.post("/workspaces/{ws_id}/links/{link_id}")
def update_link(ws_id: str, link_id: int, body: LinkUpdate) -> dict:
    if body.status not in ("confirmed", "rejected", "inferred"):
        raise HTTPException(400, "status must be confirmed, rejected or inferred")
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE cross_edges SET status = ? WHERE id = ? AND workspace_id = ?",
            (body.status, link_id, ws_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "link not found")
    finally:
        conn.close()
    return {"id": link_id, "status": body.status}


@router.get("/workspaces/{ws_id}/events")
def events(ws_id: str, after_id: int = 0):
    def stream():
        last_id = after_id
        last_beat = time.monotonic()
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT * FROM events WHERE workspace_id = ? AND id > ? ORDER BY id LIMIT 200",
                    (ws_id, last_id)).fetchall()
            finally:
                conn.close()
            for r in rows:
                last_id = r["id"]
                payload = row_to_dict(r, ("payload",))
                yield f"event: {r['type']}\ndata: {json.dumps(payload)}\n\n"
            if rows:
                last_beat = time.monotonic()
            elif time.monotonic() - last_beat > 15:
                last_beat = time.monotonic()
                yield ": ping\n\n"
            time.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")
