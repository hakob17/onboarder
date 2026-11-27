import json

from ..db import get_conn, row_to_dict


def persist_analysis(workspace_id: str, project_id: str, generic, nodes: list[dict],
                     edges: list[dict], stats: dict) -> None:
    conn = get_conn()
    try:
        conn.execute("BEGIN")
        for table in ("files", "symbols", "candidates", "nodes", "edges"):
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        conn.executemany(
            "INSERT INTO files(project_id, path, language, loc, hash) VALUES(?,?,?,?,?)",
            [(project_id, f.path, f.language, f.loc, f.sha) for f in generic.files],
        )
        conn.executemany(
            "INSERT INTO symbols(project_id, file, kind, name, parent, line_start, line_end) VALUES(?,?,?,?,?,?,?)",
            [(project_id, s["file"], s["kind"], s["name"], s["parent"], s["line_start"], s["line_end"])
             for s in generic.symbols],
        )
        conn.executemany(
            "INSERT INTO candidates(project_id, file, line, kind, value) VALUES(?,?,?,?,?)",
            [(project_id, c["file"], c["line"], c["kind"], c["value"]) for c in generic.candidates],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO nodes(id, workspace_id, project_id, kind, name, qualified_name,"
            " file, line_start, line_end, metadata, confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(n["id"], workspace_id, project_id, n["kind"], n["name"], n.get("qualified_name"),
              n.get("file"), n.get("line_start"), n.get("line_end"),
              json.dumps(n.get("metadata", {})), n.get("confidence", 1.0)) for n in nodes],
        )
        conn.executemany(
            "INSERT INTO edges(workspace_id, project_id, src, dst, kind, confidence, evidence)"
            " VALUES(?,?,?,?,?,?,?)",
            [(workspace_id, project_id, e["src"], e["dst"], e["kind"], e.get("confidence", 1.0),
              json.dumps(e.get("evidence", []))) for e in edges],
        )
        conn.execute("UPDATE projects SET stats = ? WHERE id = ?", (json.dumps(stats), project_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_graph(workspace_id: str, project_id: str | None = None) -> dict:
    conn = get_conn()
    try:
        if project_id:
            node_rows = conn.execute(
                "SELECT * FROM nodes WHERE workspace_id = ? AND project_id = ?",
                (workspace_id, project_id)).fetchall()
            edge_rows = conn.execute(
                "SELECT * FROM edges WHERE workspace_id = ? AND project_id = ?",
                (workspace_id, project_id)).fetchall()
        else:
            node_rows = conn.execute(
                "SELECT * FROM nodes WHERE workspace_id = ?", (workspace_id,)).fetchall()
            edge_rows = conn.execute(
                "SELECT * FROM edges WHERE workspace_id = ?", (workspace_id,)).fetchall()
        cross_rows = conn.execute(
            "SELECT * FROM cross_edges WHERE workspace_id = ?", (workspace_id,)).fetchall()
        return {
            "nodes": [row_to_dict(r, ("metadata",)) for r in node_rows],
            "edges": [row_to_dict(r, ("evidence",)) for r in edge_rows],
            "cross_edges": [row_to_dict(r, ("evidence",)) for r in cross_rows],
        }
    finally:
        conn.close()


def get_node(workspace_id: str, node_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM nodes WHERE workspace_id = ? AND id = ?",
            (workspace_id, node_id)).fetchone()
        return row_to_dict(row, ("metadata",)) if row else None
    finally:
        conn.close()


def node_detail(workspace_id: str, node_id: str) -> dict | None:
    node = get_node(workspace_id, node_id)
    if node is None:
        return None
    conn = get_conn()
    try:
        out_rows = conn.execute(
            "SELECT e.*, n.name AS dst_name, n.kind AS dst_kind FROM edges e"
            " JOIN nodes n ON n.id = e.dst WHERE e.workspace_id = ? AND e.src = ?",
            (workspace_id, node_id)).fetchall()
        in_rows = conn.execute(
            "SELECT e.*, n.name AS src_name, n.kind AS src_kind FROM edges e"
            " JOIN nodes n ON n.id = e.src WHERE e.workspace_id = ? AND e.dst = ?",
            (workspace_id, node_id)).fetchall()
        card_row = conn.execute(
            "SELECT card FROM summaries WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
            (node_id,)).fetchone()
        node["out_edges"] = [row_to_dict(r, ("evidence",)) for r in out_rows]
        node["in_edges"] = [row_to_dict(r, ("evidence",)) for r in in_rows]
        node["card"] = json.loads(card_row["card"]) if card_row else None
        return node
    finally:
        conn.close()


def trace(workspace_id: str, from_id: str, to_id: str | None = None, max_depth: int = 10) -> list[list[str]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            WITH RECURSIVE walk(node, depth, path) AS (
              SELECT :from_id, 0, :from_id
              UNION ALL
              SELECT e.dst, w.depth + 1, w.path || '|' || e.dst
              FROM edges e JOIN walk w ON e.src = w.node
              WHERE e.workspace_id = :ws
                AND w.depth < :max_depth
                AND instr('|' || w.path || '|', '|' || e.dst || '|') = 0
            )
            SELECT path FROM walk
            """,
            {"from_id": from_id, "ws": workspace_id, "max_depth": max_depth},
        ).fetchall()
        seen: set[str] = set()
        paths = []
        for r in rows:
            if "|" in r["path"] and r["path"] not in seen:
                seen.add(r["path"])
                paths.append(r["path"].split("|"))
        if to_id:
            return [p for p in paths if p[-1] == to_id][:50]
        src_rows = conn.execute(
            "SELECT DISTINCT src FROM edges WHERE workspace_id = ?", (workspace_id,)).fetchall()
        has_out = {r["src"] for r in src_rows}
        full = [p for p in paths if p[-1] not in has_out]
        return (full or paths)[:50]
    finally:
        conn.close()


def workspace_overview(workspace_id: str) -> dict:
    """Repo-level view: each project with its node counts, plus cross-project links
    aggregated by (source repo → target repo) with the underlying connections."""
    conn = get_conn()
    try:
        projects = [dict(r) for r in conn.execute(
            "SELECT id, name, stack, status FROM projects WHERE workspace_id = ? ORDER BY created_at",
            (workspace_id,)).fetchall()]
        counts = conn.execute(
            "SELECT project_id, kind, COUNT(*) AS n FROM nodes WHERE workspace_id = ?"
            " GROUP BY project_id, kind", (workspace_id,)).fetchall()
        rows = conn.execute(
            "SELECT ns.project_id AS src_proj, nd.project_id AS dst_proj, ce.kind AS kind,"
            "       ce.status AS status, ce.confidence AS confidence, ce.src AS src, ce.dst AS dst,"
            "       ns.name AS src_name, nd.name AS dst_name, ns.kind AS src_kind, nd.kind AS dst_kind,"
            "       ns.file AS src_file, ns.line_start AS src_line"
            " FROM cross_edges ce"
            " JOIN nodes ns ON ns.id = ce.src AND ns.workspace_id = ce.workspace_id"
            " JOIN nodes nd ON nd.id = ce.dst AND nd.workspace_id = ce.workspace_id"
            " WHERE ce.workspace_id = ? AND ce.status != 'rejected'", (workspace_id,)).fetchall()
    finally:
        conn.close()

    per_counts: dict[str, dict] = {}
    totals: dict[str, int] = {}
    for c in counts:
        per_counts.setdefault(c["project_id"], {})[c["kind"]] = c["n"]
        totals[c["project_id"]] = totals.get(c["project_id"], 0) + c["n"]
    for p in projects:
        p["name"] = p["name"].split("/")[-1] or p["name"]
        p["counts"] = per_counts.get(p["id"], {})
        p["total"] = totals.get(p["id"], 0)

    # One wire per repo PAIR (unordered): a pair may carry calls in either direction and
    # shared-table links at once — collapse them all into a single link, but keep each
    # underlying connection's own direction so the drill-down can show real src → dst.
    CALL_KINDS = {"CALLS_SERVICE", "CALLS_ENDPOINT", "HTTP", "HTTP_CALL", "RPC"}
    links: dict[tuple, dict] = {}
    for r in rows:
        sp, dp = r["src_proj"], r["dst_proj"]
        if not sp or not dp or sp == dp:
            continue
        key = tuple(sorted((sp, dp)))
        link = links.setdefault(key, {
            "src_project": key[0], "dst_project": key[1], "count": 0,
            "kinds": {}, "confirmed": False, "directed": False,
            "_dir": {}, "connections": [],
        })
        link["count"] += 1
        link["kinds"][r["kind"]] = link["kinds"].get(r["kind"], 0) + 1
        if r["status"] == "confirmed":
            link["confirmed"] = True
        if r["kind"] in CALL_KINDS:  # tally call direction to orient the wire's arrow
            link["_dir"][(sp, dp)] = link["_dir"].get((sp, dp), 0) + 1
        if len(link["connections"]) < 300:
            link["connections"].append({
                "src": r["src"], "src_name": r["src_name"], "src_kind": r["src_kind"],
                "src_file": r["src_file"], "src_line": r["src_line"], "src_project": sp,
                "dst": r["dst"], "dst_name": r["dst_name"], "dst_kind": r["dst_kind"],
                "dst_project": dp, "kind": r["kind"], "confidence": r["confidence"],
                "status": r["status"],
            })

    out_links = []
    for link in links.values():
        dirs = link.pop("_dir")
        if dirs:  # orient the wire toward the repo that receives the most calls
            (sp, dp), _ = max(dirs.items(), key=lambda kv: kv[1])
            link["src_project"], link["dst_project"] = sp, dp
            link["directed"] = True
        out_links.append(link)
    # busiest wires first so they win the z-order and read as the backbone
    out_links.sort(key=lambda l: l["count"], reverse=True)
    return {"projects": projects, "links": out_links}
