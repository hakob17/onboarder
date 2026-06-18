import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import trackers
from ..config import llm_enabled
from ..db import get_conn
from ..trackers.ado import AdoClient
from ..trackers.jira import JiraClient

router = APIRouter(tags=["trackers"])


def _http_detail(e: httpx.HTTPStatusError) -> str:
    code = e.response.status_code
    if code in (401, 403):
        return "credentials rejected by the tracker"
    if code == 404:
        return "not found — check the URL/org/project"
    return f"tracker returned HTTP {code}"


@router.get("/trackers/status")
def status() -> dict:
    return trackers.status()


class JiraCreds(BaseModel):
    base_url: str
    email: str
    api_token: str


@router.put("/trackers/jira")
def set_jira(body: JiraCreds) -> dict:
    if not (body.base_url.strip() and body.email.strip() and body.api_token.strip()):
        raise HTTPException(400, "base_url, email and api_token are all required")
    client = JiraClient(body.base_url.strip(), body.email.strip(), body.api_token.strip())
    try:
        client.whoami()
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, f"Jira: {_http_detail(e)}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"could not reach Jira: {e}") from e
    trackers.save_jira(body.base_url.strip(), body.email.strip(), body.api_token.strip())
    return trackers.status()


class AdoCreds(BaseModel):
    org: str
    project: str
    pat: str


@router.put("/trackers/ado")
def set_ado(body: AdoCreds) -> dict:
    if not (body.org.strip() and body.project.strip() and body.pat.strip()):
        raise HTTPException(400, "org, project and pat are all required")
    client = AdoClient(body.org.strip(), body.project.strip(), body.pat.strip())
    try:
        client.validate()
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, f"Azure DevOps: {_http_detail(e)}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"could not reach Azure DevOps: {e}") from e
    trackers.save_ado(body.org.strip(), body.project.strip(), body.pat.strip())
    return trackers.status()


@router.delete("/trackers/jira")
def del_jira() -> dict:
    trackers.clear_jira()
    return trackers.status()


@router.delete("/trackers/ado")
def del_ado() -> dict:
    trackers.clear_ado()
    return trackers.status()


@router.get("/trackers/{source}/issue/{key}")
def get_issue(source: str, key: str) -> dict:
    try:
        return trackers.get_ticket(source, key)
    except LookupError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, _http_detail(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"could not reach the tracker: {e}") from e


class AnalyzeBody(BaseModel):
    # only used when source == "manual"
    title: str | None = None
    body: str | None = None


@router.post("/workspaces/{ws_id}/tickets/{source}/{key}/analyze")
def analyze(ws_id: str, source: str, key: str, body: AnalyzeBody | None = None):
    if not llm_enabled():
        raise HTTPException(503, "LLM features disabled: set an Anthropic API key")
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (ws_id,)).fetchone() is None:
            raise HTTPException(404, "workspace not found")
    finally:
        conn.close()

    if source == "manual":
        b = body or AnalyzeBody()
        if not (b.body or "").strip():
            raise HTTPException(400, "manual ticket requires a body")
        ticket = {
            "source": "manual", "key": key or "ticket",
            "title": (b.title or "").strip() or "Pasted ticket",
            "body": b.body.strip(), "type": None, "status": None,
            "labels": [], "comments": [], "url": None,
        }
    else:
        try:
            ticket = trackers.get_ticket(source, key)
        except LookupError as e:
            raise HTTPException(400, str(e)) from e
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        except httpx.HTTPError as e:
            raise HTTPException(502, f"could not fetch ticket: {e}") from e

    from ..llm.fix_agent import sse_format, stream_fix
    prompt = trackers.ticket_to_prompt(ticket)

    def gen():
        # surface the resolved ticket first so the UI can show what's being analyzed
        yield sse_format("ticket", ticket)
        for event, data in stream_fix(ws_id, ticket, prompt):
            yield sse_format(event, data)

    return StreamingResponse(gen(), media_type="text/event-stream")


class CommentBody(BaseModel):
    text: str


@router.post("/trackers/{source}/issue/{key}/comment")
def comment(source: str, key: str, body: CommentBody) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "comment text is empty")
    try:
        url = trackers.post_comment(source, key, body.text.strip())
    except LookupError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except httpx.HTTPStatusError as e:
        detail = _http_detail(e)
        if e.response.status_code in (401, 403):
            detail += " — the token needs write/comment scope"
        raise HTTPException(400, detail) from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"could not reach the tracker: {e}") from e
    return {"ok": True, "url": url}
