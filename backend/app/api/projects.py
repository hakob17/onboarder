from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from ..analysis.ingest import IngestError, detect_projects, extract_zip
from ..analysis.runner import analyze_in_background
from ..config import DATA_DIR, MAX_ZIP_MB
from ..db import get_conn, new_id, now, row_to_dict

router = APIRouter(tags=["projects"])


def _workspace_or_404(ws_id: str) -> None:
    conn = get_conn()
    try:
        if conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (ws_id,)).fetchone() is None:
            raise HTTPException(404, "workspace not found")
    finally:
        conn.close()


@router.post("/workspaces/{ws_id}/projects")
def upload_project(ws_id: str, file: UploadFile) -> dict:
    _workspace_or_404(ws_id)
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "upload must be a .zip file")
    upload_id = new_id("up")
    upload_dir = DATA_DIR / "workspaces" / ws_id / "uploads" / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    zip_path = upload_dir / "source.zip"
    max_bytes = MAX_ZIP_MB * 1024 * 1024
    written = 0
    with open(zip_path, "wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                out.close()
                zip_path.unlink(missing_ok=True)
                raise HTTPException(413, f"zip exceeds {MAX_ZIP_MB} MB limit")
            out.write(chunk)
    src_dir = upload_dir / "src"
    try:
        extract_zip(zip_path, src_dir)
    except IngestError as e:
        raise HTTPException(400, str(e)) from e

    base_name = Path(file.filename or "project.zip").stem
    created = []
    conn = get_conn()
    try:
        for rel_root, stack in detect_projects(src_dir):
            project_id = new_id("p")
            name = base_name if rel_root in (".", base_name) else f"{base_name}/{rel_root}"
            root_rel = Path("workspaces") / ws_id / "uploads" / upload_id / "src"
            if rel_root != ".":
                root_rel = root_rel / rel_root
            conn.execute(
                "INSERT INTO projects(id, workspace_id, name, root_path, stack, status, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (project_id, ws_id, name, root_rel.as_posix(), stack, "pending", now()),
            )
            created.append({"id": project_id, "name": name, "stack": stack, "status": "pending"})
        conn.commit()
    finally:
        conn.close()
    for p in created:
        analyze_in_background(ws_id, p["id"])
    return {"projects": created}


@router.post("/workspaces/{ws_id}/projects/{project_id}/reanalyze")
def reanalyze(ws_id: str, project_id: str) -> dict:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM projects WHERE id = ? AND workspace_id = ?",
            (project_id, ws_id)).fetchone()
        if row is None:
            raise HTTPException(404, "project not found")
        conn.execute("UPDATE projects SET status = 'pending', error = NULL WHERE id = ?",
                     (project_id,))
        conn.commit()
    finally:
        conn.close()
    analyze_in_background(ws_id, project_id)
    return {"id": project_id, "status": "pending"}


class LocalProject(BaseModel):
    path: str


@router.post("/workspaces/{ws_id}/projects/local")
def add_local_project(ws_id: str, body: LocalProject) -> dict:
    """Analyze a folder in place — no upload, nothing copied. Used by the
    VS Code extension and local CLI flows."""
    _workspace_or_404(ws_id)
    root = Path(body.path).expanduser()
    if not root.is_absolute():
        raise HTTPException(400, "path must be absolute")
    root = root.resolve()
    if not root.is_dir():
        raise HTTPException(400, f"not a directory: {root}")

    created = []
    conn = get_conn()
    try:
        existing = {r["root_path"] for r in conn.execute(
            "SELECT root_path FROM projects WHERE workspace_id = ?", (ws_id,)).fetchall()}
        for rel_root, stack in detect_projects(root):
            project_root = root if rel_root == "." else root / rel_root
            if str(project_root) in existing:
                continue
            project_id = new_id("p")
            name = project_root.name
            conn.execute(
                "INSERT INTO projects(id, workspace_id, name, root_path, stack, status, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (project_id, ws_id, name, str(project_root), stack, "pending", now()),
            )
            created.append({"id": project_id, "name": name, "stack": stack,
                            "status": "pending", "root_path": str(project_root)})
        conn.commit()
    finally:
        conn.close()
    for p in created:
        analyze_in_background(ws_id, p["id"])
    return {"projects": created}


@router.delete("/workspaces/{ws_id}/projects/{project_id}")
def delete_project(ws_id: str, project_id: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM projects WHERE id = ? AND workspace_id = ?", (project_id, ws_id))
        conn.execute(
            "DELETE FROM cross_edges WHERE workspace_id = ? AND (src LIKE ? OR dst LIKE ?)",
            (ws_id, f"{project_id}:%", f"{project_id}:%"))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "project not found")
    finally:
        conn.close()
    return {"deleted": project_id}


@router.get("/workspaces/{ws_id}/projects")
def list_projects(ws_id: str) -> list[dict]:
    _workspace_or_404(ws_id)
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM projects WHERE workspace_id = ? ORDER BY created_at", (ws_id,)).fetchall()
        return [row_to_dict(r, ("stats",)) for r in rows]
    finally:
        conn.close()


@router.get("/workspaces/{ws_id}/projects/{project_id}/files")
def project_files(ws_id: str, project_id: str) -> dict:
    conn = get_conn()
    try:
        project = conn.execute(
            "SELECT * FROM projects WHERE id = ? AND workspace_id = ?",
            (project_id, ws_id)).fetchone()
        if project is None:
            raise HTTPException(404, "project not found")
        rows = conn.execute(
            "SELECT path, language, loc FROM files WHERE project_id = ? ORDER BY path",
            (project_id,)).fetchall()
    finally:
        conn.close()
    root: dict = {"name": project["name"], "type": "dir", "children": {}}
    for r in rows:
        parts = r["path"].split("/")
        cursor = root
        for part in parts[:-1]:
            cursor = cursor["children"].setdefault(part, {"name": part, "type": "dir", "children": {}})
        cursor["children"][parts[-1]] = {
            "name": parts[-1], "type": "file", "language": r["language"], "loc": r["loc"],
        }

    def _materialize(node: dict) -> dict:
        if node["type"] == "dir":
            node["children"] = [_materialize(c) for _, c in sorted(node["children"].items())]
        return node

    return {"project_id": project_id, "status": project["status"], "tree": _materialize(root)}
