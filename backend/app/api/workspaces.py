import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import DATA_DIR
from ..db import get_conn, new_id, now, row_to_dict

router = APIRouter(tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str


@router.post("/workspaces")
def create_workspace(body: WorkspaceCreate) -> dict:
    ws_id = new_id("ws")
    conn = get_conn()
    try:
        conn.execute("INSERT INTO workspaces(id, name, created_at) VALUES(?,?,?)",
                     (ws_id, body.name, now()))
        conn.commit()
    finally:
        conn.close()
    return {"id": ws_id, "name": body.name}


@router.get("/workspaces")
def list_workspaces() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT w.*, (SELECT COUNT(*) FROM projects p WHERE p.workspace_id = w.id) AS project_count"
            " FROM workspaces w ORDER BY w.created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/workspaces/{ws_id}")
def get_workspace(ws_id: str) -> dict:
    conn = get_conn()
    try:
        ws = conn.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
        if ws is None:
            raise HTTPException(404, "workspace not found")
        projects = conn.execute(
            "SELECT * FROM projects WHERE workspace_id = ? ORDER BY created_at", (ws_id,)).fetchall()
        out = dict(ws)
        out["projects"] = [row_to_dict(p, ("stats",)) for p in projects]
        return out
    finally:
        conn.close()


@router.delete("/workspaces/{ws_id}")
def delete_workspace(ws_id: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
        conn.execute("DELETE FROM nodes WHERE workspace_id = ?", (ws_id,))
        conn.execute("DELETE FROM edges WHERE workspace_id = ?", (ws_id,))
        conn.execute("DELETE FROM events WHERE workspace_id = ?", (ws_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "workspace not found")
    finally:
        conn.close()
    shutil.rmtree(DATA_DIR / "workspaces" / ws_id, ignore_errors=True)
    return {"deleted": ws_id}
