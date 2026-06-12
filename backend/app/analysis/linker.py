"""Cross-project linker (Phase 5).

Matches one project's outbound calls to another project's endpoints using,
in order of strength: resolved host ↔ project identity, normalized path
templates, and HTTP method. Also detects tables shared by several projects.
Inferred links are replaced on each run; confirmed/rejected ones persist.
"""

import json
import threading

from ..config import llm_enabled, resolve_root
from ..db import emit_event, get_conn, now, row_to_dict
from .configs import harvest, norm_path, norm_token, resolve_template, split_url

_LOCK = threading.Lock()
MIN_SCORE = 0.55


def _load(workspace_id: str):
    conn = get_conn()
    try:
        projects = [dict(r) for r in conn.execute(
            "SELECT * FROM projects WHERE workspace_id = ? AND status = 'ready'",
            (workspace_id,)).fetchall()]
        nodes = [row_to_dict(r, ("metadata",)) for r in conn.execute(
            "SELECT * FROM nodes WHERE workspace_id = ? AND kind IN ('entry_point','outbound_call','table')",
            (workspace_id,)).fetchall()]
        return projects, nodes
    finally:
        conn.close()


def _score(outbound, endpoint, host: str | None, target_proj_tokens: set[str],
           internal_hosts: set[str]) -> float:
    score = 0.0
    o_method = (outbound["metadata"].get("http_method") or "ANY").upper()
    e_method = (endpoint["metadata"].get("http_method") or "ANY").upper()
    if o_method in ("ANY", "CALL") or e_method == "ANY":
        score += 0.15
    elif o_method == e_method:
        score += 0.35
    else:
        return 0.0

    o_path = norm_path(split_url(outbound["_resolved"])[1])
    e_path = norm_path(endpoint["metadata"].get("path") or endpoint["name"])
    if o_path == e_path:
        score += 0.5
    elif o_path.endswith(e_path) or e_path.endswith(o_path):
        score += 0.3
    else:
        return 0.0

    if host:
        htok = norm_token(host)
        if htok and any(htok == t or htok in t or t in htok for t in target_proj_tokens if t):
            score += 0.25
        elif host in internal_hosts:
            score += 0.1
    service = outbound["metadata"].get("service")
    if service and norm_token(service) in target_proj_tokens:
        score += 0.25
    return min(score, 1.0)


def _adjudicate_llm(outbound, candidates) -> int | None:
    """Ask the model to pick among near-tied endpoint candidates. Returns index or None."""
    if not llm_enabled():
        return None
    try:
        from pydantic import BaseModel

        from ..llm import get_client

        class Verdict(BaseModel):
            winner_index: int
            confident: bool

        lines = [f"{i}: project={c['project_id']} endpoint={c['name']}" for i, c in enumerate(candidates)]
        client = get_client()
        resp = client.messages.parse(
            model="claude-opus-4-8",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": ("An outbound HTTP call needs to be matched to the endpoint it targets.\n"
                            f"Call: {outbound['name']} (resolved: {outbound['_resolved']})\n"
                            "Candidates:\n" + "\n".join(lines) +
                            "\nPick the winner_index, or set confident=false if none clearly matches."),
            }],
            output_format=Verdict,
        )
        v = resp.parsed_output
        return v.winner_index if v.confident and 0 <= v.winner_index < len(candidates) else None
    except Exception:
        return None


def link_workspace(workspace_id: str) -> dict:
    with _LOCK:
        return _link(workspace_id)


def _link(workspace_id: str) -> dict:
    projects, nodes = _load(workspace_id)
    if len(projects) < 2:
        return {"links": 0, "shared_tables": 0, "skipped": "needs 2+ ready projects"}

    cfg = {p["id"]: harvest(resolve_root(p["root_path"])) for p in projects}
    env_union: dict[str, str] = {}
    internal_hosts: set[str] = set()
    for c in cfg.values():
        env_union.update(c["env"])
        internal_hosts.update(c["services"])
    proj_tokens = {
        p["id"]: {norm_token(p["name"].split("/")[-1]), norm_token(p["root_path"].split("/")[-1])}
        for p in projects
    }

    endpoints = [n for n in nodes if n["kind"] == "entry_point"]
    outbounds = [n for n in nodes if n["kind"] == "outbound_call"]
    tables = [n for n in nodes if n["kind"] == "table"]

    new_links: list[dict] = []
    for ob in outbounds:
        template = ob["metadata"].get("url_template") or ""
        ob["_resolved"] = resolve_template(template, env_union)
        host, _ = split_url(ob["_resolved"])
        scored = []
        for ep in endpoints:
            if ep["project_id"] == ob["project_id"]:
                continue
            s = _score(ob, ep, host, proj_tokens.get(ep["project_id"], set()), internal_hosts)
            if s >= MIN_SCORE:
                scored.append((s, ep))
        if not scored:
            continue
        scored.sort(key=lambda t: -t[0])
        best_score, best = scored[0]
        ties = [ep for s, ep in scored if best_score - s < 0.1]
        if len(ties) > 1:
            idx = _adjudicate_llm(ob, ties)
            if idx is not None:
                best = ties[idx]
                best_score = max(best_score, 0.8)
            else:
                best_score = min(best_score, 0.6)
        evidence = [
            {"file": ob.get("file") or "", "line": ob.get("line_start") or 0,
             "snippet": f"call site: {ob['name']}"},
            {"file": best.get("file") or "", "line": best.get("line_start") or 0,
             "snippet": f"endpoint: {best['name']}"},
        ]
        if ob["_resolved"] != template:
            evidence.append({"file": "", "line": 0, "snippet": f"resolved: {template} -> {ob['_resolved']}"})
        new_links.append({"src": ob["id"], "dst": best["id"], "kind": "CALLS_SERVICE",
                          "confidence": round(best_score, 2), "evidence": evidence})

    by_table: dict[str, list[dict]] = {}
    for t in tables:
        by_table.setdefault(t["name"].lower(), []).append(t)
    shared = 0
    for name, group in by_table.items():
        project_ids = {t["project_id"] for t in group}
        if len(project_ids) < 2:
            continue
        group.sort(key=lambda t: t["id"])
        anchor = group[0]
        for other in group[1:]:
            if other["project_id"] == anchor["project_id"]:
                continue
            shared += 1
            new_links.append({
                "src": anchor["id"], "dst": other["id"], "kind": "SHARED_TABLE",
                "confidence": 0.7,
                "evidence": [
                    {"file": anchor.get("file") or "", "line": anchor.get("line_start") or 0,
                     "snippet": f"table '{name}' in {anchor['project_id']}"},
                    {"file": other.get("file") or "", "line": other.get("line_start") or 0,
                     "snippet": f"table '{name}' in {other['project_id']}"},
                ],
            })

    conn = get_conn()
    try:
        kept = conn.execute(
            "SELECT src, dst, kind FROM cross_edges WHERE workspace_id = ? AND status != 'inferred'",
            (workspace_id,)).fetchall()
        kept_keys = {(r["src"], r["dst"], r["kind"]) for r in kept}
        conn.execute("DELETE FROM cross_edges WHERE workspace_id = ? AND status = 'inferred'",
                     (workspace_id,))
        inserted = 0
        for link in new_links:
            if (link["src"], link["dst"], link["kind"]) in kept_keys:
                continue
            conn.execute(
                "INSERT INTO cross_edges(workspace_id, src, dst, kind, confidence, evidence, status)"
                " VALUES(?,?,?,?,?,?,'inferred')",
                (workspace_id, link["src"], link["dst"], link["kind"], link["confidence"],
                 json.dumps(link["evidence"])))
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    result = {"links": inserted, "shared_tables": shared, "at": now()}
    emit_event(workspace_id, None, "link_completed", result)
    return result
