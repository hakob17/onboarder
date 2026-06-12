"""Graph snapshots and diffing (Phase 7).

Node ids are deterministic, so a diff is a set comparison: nodes by id, edges
by (src, dst, kind). "Changed" means a significant metadata field differs —
line drift alone never counts. Baselines come from three places: manual saves,
a rolling auto-snapshot taken right before re-analysis, and git refs (the ref
is exported with `git archive` to a temp dir and run through the same pipeline
with the same project ids, so ids stay comparable).
"""

import json
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..db import get_conn, now
from .graph import fetch_graph

AUTO_KEEP = 5
AUTO_DEBOUNCE_SECONDS = 15
SIGNIFICANT_KEYS = ("columns", "url_template", "http_method", "path", "entity", "layer", "service")


def _store(workspace_id: str, label: str, kind: str, git_ref: str | None, graph: dict) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO snapshots(workspace_id, label, kind, git_ref, created_at, graph)"
            " VALUES(?,?,?,?,?,?)",
            (workspace_id, label, kind, git_ref, now(), json.dumps(graph)))
        conn.commit()
        snap_id = cur.lastrowid
    finally:
        conn.close()
    return {
        "id": snap_id, "label": label, "kind": kind, "git_ref": git_ref,
        "node_count": len(graph["nodes"]), "edge_count": len(graph["edges"]),
    }


def capture_snapshot(workspace_id: str, label: str = "baseline", kind: str = "manual",
                     git_ref: str | None = None) -> dict:
    graph = fetch_graph(workspace_id)
    return _store(workspace_id, label, kind, git_ref, graph)


def maybe_auto_snapshot(workspace_id: str) -> None:
    """Rolling 'previous state' captured before a (re-)analysis overwrites it."""
    graph = fetch_graph(workspace_id)
    if not graph["nodes"]:
        return
    conn = get_conn()
    try:
        last = conn.execute(
            "SELECT created_at FROM snapshots WHERE workspace_id = ? AND kind = 'auto'"
            " ORDER BY id DESC LIMIT 1", (workspace_id,)).fetchone()
        if last:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(last["created_at"])).total_seconds()
            if age < AUTO_DEBOUNCE_SECONDS:
                return
    finally:
        conn.close()
    _store(workspace_id, "auto", "auto", None, graph)
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM snapshots WHERE workspace_id = ? AND kind = 'auto' AND id NOT IN ("
            " SELECT id FROM snapshots WHERE workspace_id = ? AND kind = 'auto'"
            " ORDER BY id DESC LIMIT ?)",
            (workspace_id, workspace_id, AUTO_KEEP))
        conn.commit()
    finally:
        conn.close()


def capture_git_snapshot(workspace_id: str, git_ref: str, label: str | None = None) -> dict:
    """Analyze each local git project at `git_ref` (in a temp export) and snapshot that."""
    from .runner import build_project_graph

    conn = get_conn()
    try:
        projects = [dict(r) for r in conn.execute(
            "SELECT * FROM projects WHERE workspace_id = ? AND status = 'ready'",
            (workspace_id,)).fetchall()]
    finally:
        conn.close()

    current = fetch_graph(workspace_id)
    all_nodes: list = []
    all_edges: list = []
    analyzed_any = False

    for p in projects:
        root = Path(p["root_path"])
        if not root.is_absolute() or not root.is_dir():
            all_nodes += [n for n in current["nodes"] if n["project_id"] == p["id"]]
            all_edges += [e for e in current["edges"] if e.get("project_id") == p["id"]]
            continue
        try:
            gitroot = Path(subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True, timeout=10).stdout.strip())
            rel = root.relative_to(gitroot)
            with tempfile.TemporaryDirectory(prefix="onboarder-ref-") as td:
                tar_path = Path(td) / "ref.tar"
                subprocess.run(
                    ["git", "-C", str(gitroot), "archive", "--format=tar", "-o", str(tar_path), git_ref],
                    capture_output=True, text=True, check=True, timeout=60)
                extract_dir = Path(td) / "src"
                extract_dir.mkdir()
                with tarfile.open(tar_path) as tf:
                    tf.extractall(extract_dir, filter="data")
                src = extract_dir / rel
                if not src.is_dir():
                    raise FileNotFoundError(f"{rel} not present at {git_ref}")
                _, nodes, edges, _stats = build_project_graph(p, src, allow_llm=False)
                for n in nodes:
                    n["workspace_id"] = workspace_id
                    n["project_id"] = p["id"]
                for e in edges:
                    e["project_id"] = p["id"]
                all_nodes += nodes
                all_edges += edges
                analyzed_any = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            all_nodes += [n for n in current["nodes"] if n["project_id"] == p["id"]]
            all_edges += [e for e in current["edges"] if e.get("project_id") == p["id"]]

    if not analyzed_any:
        raise ValueError(f"no local git project could be exported at ref '{git_ref}'")
    graph = {"nodes": all_nodes, "edges": all_edges, "cross_edges": current["cross_edges"]}
    return _store(workspace_id, label or git_ref, "git", git_ref, graph)


def list_snapshots(workspace_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, label, kind, git_ref, created_at, graph FROM snapshots"
            " WHERE workspace_id = ? ORDER BY id DESC LIMIT 30", (workspace_id,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        g = json.loads(r["graph"])
        out.append({"id": r["id"], "label": r["label"], "kind": r["kind"],
                    "git_ref": r["git_ref"], "created_at": r["created_at"],
                    "node_count": len(g["nodes"]), "edge_count": len(g["edges"])})
    return out


def delete_snapshot(workspace_id: str, snapshot_id: int) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM snapshots WHERE id = ? AND workspace_id = ?",
                           (snapshot_id, workspace_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _resolve(workspace_id: str, spec: str) -> tuple[dict, dict]:
    """spec: 'current' | 'latest' | snapshot id | label → (graph, meta)."""
    if spec == "current":
        return fetch_graph(workspace_id), {"label": "current", "kind": "current"}
    conn = get_conn()
    try:
        if spec == "latest":
            row = conn.execute(
                "SELECT * FROM snapshots WHERE workspace_id = ? ORDER BY id DESC LIMIT 1",
                (workspace_id,)).fetchone()
        elif spec.isdigit():
            row = conn.execute(
                "SELECT * FROM snapshots WHERE workspace_id = ? AND id = ?",
                (workspace_id, int(spec))).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE workspace_id = ? AND label = ?"
                " ORDER BY id DESC LIMIT 1", (workspace_id, spec)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"no snapshot matching '{spec}'")
    meta = {"id": row["id"], "label": row["label"], "kind": row["kind"],
            "git_ref": row["git_ref"], "created_at": row["created_at"]}
    return json.loads(row["graph"]), meta


def _significant(node: dict) -> dict:
    md = node.get("metadata") or {}
    return {k: md.get(k) for k in SIGNIFICANT_KEYS if md.get(k) is not None}


def compute_diff(workspace_id: str, base_spec: str = "latest", target_spec: str = "current") -> dict:
    base, base_meta = _resolve(workspace_id, base_spec)
    target, target_meta = _resolve(workspace_id, target_spec)

    base_nodes = {n["id"]: n for n in base["nodes"]}
    target_nodes = {n["id"]: n for n in target["nodes"]}
    added_nodes = [n for i, n in target_nodes.items() if i not in base_nodes]
    removed_nodes = [n for i, n in base_nodes.items() if i not in target_nodes]
    changed_nodes = []
    for node_id in base_nodes.keys() & target_nodes.keys():
        old = _significant(base_nodes[node_id])
        new = _significant(target_nodes[node_id])
        if old != new:
            keys = sorted(set(old) | set(new))
            changes = {k: [old.get(k), new.get(k)] for k in keys if old.get(k) != new.get(k)}
            changed_nodes.append({"node": target_nodes[node_id], "changes": changes})

    def edge_key(e: dict) -> tuple:
        return (e["src"], e["dst"], e["kind"])

    base_edges = {edge_key(e): e for e in [*base["edges"], *base.get("cross_edges", [])]}
    target_edges = {edge_key(e): e for e in [*target["edges"], *target.get("cross_edges", [])]}
    added_edges = [e for k, e in target_edges.items() if k not in base_edges]
    removed_edges = [e for k, e in base_edges.items() if k not in target_edges]

    stats: dict = {}
    for n in added_nodes:
        stats.setdefault(n["kind"], {"added": 0, "removed": 0, "changed": 0})["added"] += 1
    for n in removed_nodes:
        stats.setdefault(n["kind"], {"added": 0, "removed": 0, "changed": 0})["removed"] += 1
    for c in changed_nodes:
        stats.setdefault(c["node"]["kind"], {"added": 0, "removed": 0, "changed": 0})["changed"] += 1

    return {
        "base": base_meta,
        "target": target_meta,
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "stats": stats,
        "total_changes": len(added_nodes) + len(removed_nodes) + len(changed_nodes)
        + len(added_edges) + len(removed_edges),
    }
