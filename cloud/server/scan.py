"""Scan orchestrator: clone an org's connected repositories and build one shared
cross-repo map from them, reusing the engine end to end.

For each repo we run the engine's own ``detect_projects`` (so a multi-module repo
splits into real modules), register each as a project in the org's single
workspace, analyze it with the engine's extractors, and finally run the engine's
cross-project linker once — so calls, shared tables, GraphQL entities and shared
models light up *across* repositories, which is the whole point of the org space.

Clones are shallow. A GitHub token, when supplied for private repos, is injected
into the clone URL only for the subprocess call and immediately scrubbed from the
repo's git config, so it never lands on disk or in logs.
"""
import re
import shutil
import subprocess
import threading
import traceback
from pathlib import Path

from app.analysis.graph import persist_analysis
from app.analysis.ingest import detect_projects
from app.analysis.linker import link_workspace
from app.analysis.runner import build_project_graph
from app.db import emit_event, get_conn, new_id, now

from . import REPOS_DIR
from . import orgdb

# One scan per org at a time.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _org_lock(org_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(org_id, threading.Lock())


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:80] or "repo"


def _auth_url(clone_url: str, token: str | None) -> str:
    if token and clone_url.startswith("https://"):
        # token used only for this subprocess; scrubbed from git config right after.
        return clone_url.replace("https://", f"https://x-access-token:{token}@", 1)
    return clone_url


def _scrub(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def clone_or_update(clone_url: str, dest: Path, token: str | None,
                    branch: str | None) -> None:
    """Shallow-clone (or refresh) a repo into ``dest``. Token never persisted."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    args = ["git", "clone", "--depth", "1", "--single-branch"]
    if branch:
        args += ["--branch", branch]
    args += [_auth_url(clone_url, token), str(dest)]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(_scrub(proc.stderr.strip() or "git clone failed", token)[:400])
    # Make sure no credential lingers in the cloned repo's remote.
    subprocess.run(["git", "-C", str(dest), "remote", "set-url", "origin", clone_url],
                   capture_output=True, text=True)


def _register_projects(ws_id: str, repo_name: str, repo_dir: Path) -> list[dict]:
    """Run the engine's detector over a cloned repo and insert its project rows."""
    created: list[dict] = []
    roots = detect_projects(repo_dir)
    conn = get_conn()
    try:
        existing = {r["root_path"] for r in conn.execute(
            "SELECT root_path FROM projects WHERE workspace_id = ?", (ws_id,)).fetchall()}
        for rel_root, stack in roots:
            project_root = repo_dir if rel_root == "." else repo_dir / rel_root
            if str(project_root) in existing:
                continue
            project_id = new_id("p")
            # Name modules as "repo / module" so the map stays readable across repos.
            name = repo_name if rel_root == "." else f"{repo_name} / {Path(rel_root).name}"
            conn.execute(
                "INSERT INTO projects(id, workspace_id, name, root_path, stack, status, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (project_id, ws_id, name, str(project_root), stack, "pending", now()))
            created.append({"id": project_id, "name": name, "stack": stack})
        conn.commit()
    finally:
        conn.close()
    return created


def _set_project_status(project_id: str, status: str, error: str | None = None) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE projects SET status=?, error=? WHERE id=?",
                     (status, error, project_id))
        conn.commit()
    finally:
        conn.close()


def _analyze(ws_id: str, project_id: str) -> None:
    """Build + persist one project's graph (linking is done once, at the end)."""
    conn = get_conn()
    try:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    finally:
        conn.close()
    if project is None:
        return
    from app.config import resolve_root
    src_root = resolve_root(project["root_path"])
    _set_project_status(project_id, "analyzing")
    emit_event(ws_id, project_id, "analysis_started", {"stack": project["stack"]})
    try:
        generic, nodes, edges, stats = build_project_graph(
            dict(project), src_root, allow_llm=True,
            emit=lambda t, p: emit_event(ws_id, project_id, t, p))
        persist_analysis(ws_id, project_id, generic, nodes, edges, stats)
        _set_project_status(project_id, "ready")
        emit_event(ws_id, project_id, "analysis_completed",
                   {"nodes": len(nodes), "edges": len(edges), **stats})
    except Exception as e:
        _set_project_status(project_id, "failed", f"{e}")
        emit_event(ws_id, project_id, "analysis_failed",
                   {"error": str(e), "trace": traceback.format_exc()[-1500:]})


def scan_org(org_id: str, token: str | None = None) -> None:
    """Full scan of one org, in a background thread. Clones every connected repo,
    analyzes it, then links the whole workspace once."""
    lock = _org_lock(org_id)
    if not lock.acquire(blocking=False):
        return  # a scan is already running for this org
    try:
        org = orgdb.get_org(org_id)
        if not org:
            return
        ws_id = org["workspace_id"]
        repos = orgdb.list_repos(org_id)
        orgdb.set_scan_status(org_id, "scanning", f"Starting scan of {len(repos)} repositories…")
        analyzed = 0
        for repo in repos:
            dest = REPOS_DIR / org_id / _safe(repo["name"])
            try:
                orgdb.set_repo_status(repo["id"], "cloning")
                orgdb.set_scan_status(org_id, "scanning", f"Cloning {repo['name']}…")
                tok = token if repo["private"] else None
                clone_or_update(repo["clone_url"], dest, tok, repo.get("default_branch"))
                orgdb.set_repo_status(repo["id"], "analyzing")
                orgdb.set_scan_status(org_id, "scanning", f"Analyzing {repo['name']}…")
                projects = _register_projects(ws_id, repo["name"], dest)
                for p in projects:
                    _analyze(ws_id, p["id"])
                orgdb.set_repo_status(repo["id"], "ready",
                                      f"{len(projects)} project(s)")
                analyzed += 1
            except Exception as e:  # keep going; one bad repo shouldn't fail the org
                orgdb.set_repo_status(repo["id"], "failed", str(e)[:300])
                emit_event(ws_id, None, "repo_failed", {"repo": repo["name"], "error": str(e)[:300]})
        orgdb.set_scan_status(org_id, "scanning", "Linking cross-repo connections…")
        try:
            link_workspace(ws_id)
        except Exception as e:
            emit_event(ws_id, None, "link_failed", {"error": str(e)})
        orgdb.set_scan_status(org_id, "ready",
                              f"Scanned {analyzed}/{len(repos)} repositories", stamp_last=True)
    except Exception as e:
        orgdb.set_scan_status(org_id, "failed", str(e)[:300], stamp_last=True)
    finally:
        lock.release()


def scan_org_async(org_id: str, token: str | None = None) -> None:
    threading.Thread(target=scan_org, args=(org_id, token), daemon=True).start()
