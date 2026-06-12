from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import llm_enabled
from ..db import get_conn

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("/workspaces/{ws_id}/chat")
def chat(ws_id: str, body: ChatRequest):
    if not llm_enabled():
        raise HTTPException(503, "LLM features disabled: set ANTHROPIC_API_KEY")
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (ws_id,)).fetchone() is None:
            raise HTTPException(404, "workspace not found")
    finally:
        conn.close()
    from ..llm.chat_agent import sse_format, stream_chat

    def stream():
        for event, data in stream_chat(ws_id, body.message):
            yield sse_format(event, data)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/workspaces/{ws_id}/chat/history")
def history(ws_id: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM chat_messages WHERE workspace_id = ?"
            " ORDER BY id DESC LIMIT ?", (ws_id, min(limit, 200))).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()
