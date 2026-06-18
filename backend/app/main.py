from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import chat, graph, projects, settings, snapshots, tours, trackers, workspaces
from .config import MODEL, STATIC_DIR, llm_enabled
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="onboarder", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router)
app.include_router(projects.router)
app.include_router(graph.router)
app.include_router(chat.router)
app.include_router(settings.router)
app.include_router(snapshots.router)
app.include_router(tours.router)
app.include_router(trackers.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_enabled": llm_enabled(), "model": MODEL}


# Serve the built web UI from the same service (hosted deploy). Mounted last so
# every API route above takes precedence; no-op in local dev when unset.
if STATIC_DIR and Path(STATIC_DIR).is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
