from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..analysis import snapshots
from ..db import get_conn

router = APIRouter(tags=["snapshots"])


def _workspace_or_404(ws_id: str) -> None:
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (ws_id,)).fetchone() is None:
            raise HTTPException(404, "workspace not found")
    finally:
        conn.close()


class SnapshotCreate(BaseModel):
    label: str | None = None
    git_ref: str | None = None


@router.get("/workspaces/{ws_id}/snapshots")
def list_snapshots(ws_id: str) -> list[dict]:
    _workspace_or_404(ws_id)
    return snapshots.list_snapshots(ws_id)


@router.post("/workspaces/{ws_id}/snapshots")
def create_snapshot(ws_id: str, body: SnapshotCreate) -> dict:
    _workspace_or_404(ws_id)
    try:
        if body.git_ref:
            return snapshots.capture_git_snapshot(ws_id, body.git_ref, body.label)
        return snapshots.capture_snapshot(ws_id, body.label or "baseline")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/workspaces/{ws_id}/snapshots/{snapshot_id}")
def delete_snapshot(ws_id: str, snapshot_id: int) -> dict:
    if not snapshots.delete_snapshot(ws_id, snapshot_id):
        raise HTTPException(404, "snapshot not found")
    return {"deleted": snapshot_id}


@router.get("/workspaces/{ws_id}/diff")
def get_diff(ws_id: str, base: str = Query("latest"), target: str = Query("current")) -> dict:
    _workspace_or_404(ws_id)
    try:
        return snapshots.compute_diff(ws_id, base, target)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
