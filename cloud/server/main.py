"""Onboarder Cloud server.

Assembles one FastAPI app that:
  * reuses every engine API router (graph, workspaces, projects, chat, settings…)
    unchanged, mounted at the root — so the existing web UI works against it with
    no modification;
  * adds the org-space API under ``/api/orgs``;
  * serves a landing "org directory" at ``/`` and, at ``/space/{org_id}``, opens
    the existing map UI pinned to that org's workspace.

Importing ``server`` (this package's ``__init__``) has already put ``backend/`` on
the path and pointed ``ONBOARDER_DATA_DIR`` at ``cloud/data`` — so the imports
below resolve to the shipped engine and write to the hosted product's own db.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import chat, graph, projects, settings, snapshots, tours, trackers, workspaces
from app.config import MODEL, llm_enabled
from app.db import init_db

from . import CLOUD_ROOT, REPO_ROOT
from . import orgdb
from .orgs import router as orgs_router

_WEB = CLOUD_ROOT / "web"
_FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()           # engine schema (workspaces, projects, nodes, …)
    orgdb.init_org_db()  # org-space tables on top
    yield


app = FastAPI(title="onboarder-cloud", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Engine routers — reused verbatim, mounted at root so the web UI's "" api base hits them.
for r in (workspaces.router, projects.router, graph.router, chat.router,
          settings.router, snapshots.router, tours.router, trackers.router):
    app.include_router(r)

# Org-space API.
app.include_router(orgs_router)


@app.get("/health")
def health() -> dict:
    from app.config import BUILD
    return {"status": "ok", "product": "onboarder-cloud", "llm_enabled": llm_enabled(),
            "model": MODEL, "build": BUILD}


@app.get("/space/{org_id}")
def enter_space(org_id: str):
    """Open the org's map in the existing UI (read-only viewer experience)."""
    org = orgdb.get_org(org_id)
    if not org:
        raise HTTPException(404, "org not found")
    # The built UI reads ?ws= and ?api= from the query at boot.
    return RedirectResponse(url=f"/app/?ws={org['workspace_id']}&api=")


@app.get("/")
def landing():
    index = _WEB / "index.html"
    if not index.is_file():
        return {"service": "onboarder-cloud", "hint": "web/index.html not found"}
    return FileResponse(index)


# The existing built web UI. Assets are referenced absolutely as /assets/*, so they
# are mounted at the root; the SPA itself is served under /app.
if (_FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")
if _FRONTEND_DIST.is_dir():
    app.mount("/app", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="app")
