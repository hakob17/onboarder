from fastapi import APIRouter, HTTPException

from ..config import llm_enabled
from ..db import get_conn

router = APIRouter(tags=["tours"])


def _workspace_or_404(ws_id: str) -> None:
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (ws_id,)).fetchone() is None:
            raise HTTPException(404, "workspace not found")
    finally:
        conn.close()


@router.get("/workspaces/{ws_id}/tours")
def get_tours(ws_id: str) -> list[dict]:
    _workspace_or_404(ws_id)
    from ..llm.tours import list_tours
    return list_tours(ws_id)


@router.post("/workspaces/{ws_id}/tours")
def create_tour(ws_id: str) -> dict:
    _workspace_or_404(ws_id)
    if not llm_enabled():
        raise HTTPException(503, "LLM features disabled: add an API key in Settings")
    from ..llm.tours import generate_tour
    try:
        return generate_tour(ws_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
