"""Org-space persistence — a thin multi-tenant layer *on top of* the engine's own
schema. Orgs and their connected repositories live in the same SQLite database as
the engine's workspaces/projects/nodes, so an org simply owns one engine
``workspace`` that holds its whole cross-repo map.

Secrets are never stored in the clear: the owner key is kept only as a SHA-256
hash, and GitHub tokens are never persisted at all (they are passed per request
and used transiently — see ``github.py`` / ``scan.py``).
"""
import hashlib
import hmac
import secrets

from app.db import get_conn, new_id, now  # reused engine helpers

ORG_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs(
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  slug          TEXT,
  workspace_id  TEXT NOT NULL,
  owner_key_hash TEXT NOT NULL,
  blurb         TEXT,
  scan_status   TEXT NOT NULL DEFAULT 'idle',
  scan_detail   TEXT,
  last_scan_at  TEXT,
  created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS org_repos(
  id            TEXT PRIMARY KEY,
  org_id        TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  clone_url     TEXT NOT NULL,
  full_name     TEXT,
  default_branch TEXT,
  private       INTEGER NOT NULL DEFAULT 0,
  source        TEXT NOT NULL DEFAULT 'url',
  status        TEXT NOT NULL DEFAULT 'pending',
  detail        TEXT,
  added_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_org_repos_org ON org_repos(org_id);
"""


def init_org_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(ORG_SCHEMA)
        conn.commit()
    finally:
        conn.close()


# ── owner keys ────────────────────────────────────────────────────────────────

def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_owner_key() -> str:
    # URL-safe, ~43 chars of entropy; shown to the owner exactly once.
    return "ok_" + secrets.token_urlsafe(24)


def verify_owner_key(org_id: str, key: str | None) -> bool:
    if not key:
        return False
    conn = get_conn()
    try:
        row = conn.execute("SELECT owner_key_hash FROM orgs WHERE id = ?", (org_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    return hmac.compare_digest(row["owner_key_hash"], _hash_key(key))


# ── orgs ──────────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    s = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s or "org"


def create_org(name: str, blurb: str | None = None) -> dict:
    """Create an org, its engine workspace, and a one-time owner key."""
    org_id = new_id("org")
    ws_id = new_id("ws")
    owner_key = new_owner_key()
    conn = get_conn()
    try:
        conn.execute("INSERT INTO workspaces(id, name, created_at) VALUES(?,?,?)",
                     (ws_id, name, now()))
        conn.execute(
            "INSERT INTO orgs(id, name, slug, workspace_id, owner_key_hash, blurb, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (org_id, name, _slugify(name), ws_id, _hash_key(owner_key), blurb, now()))
        conn.commit()
    finally:
        conn.close()
    return {"id": org_id, "name": name, "workspace_id": ws_id, "owner_key": owner_key}


def get_org(org_id: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM orgs WHERE id = ?", (org_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _public_org(row: dict, repo_count: int) -> dict:
    """The shape safe to expose to any viewer — no key hash, no secrets."""
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "workspace_id": row["workspace_id"],
        "blurb": row["blurb"],
        "scan_status": row["scan_status"],
        "scan_detail": row["scan_detail"],
        "last_scan_at": row["last_scan_at"],
        "repo_count": repo_count,
        "created_at": row["created_at"],
    }


def list_orgs() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM orgs ORDER BY created_at DESC").fetchall()
        counts = dict(conn.execute(
            "SELECT org_id, COUNT(*) FROM org_repos GROUP BY org_id").fetchall())
    finally:
        conn.close()
    return [_public_org(dict(r), counts.get(r["id"], 0)) for r in rows]


def public_org(org_id: str) -> dict | None:
    row = get_org(org_id)
    if not row:
        return None
    return _public_org(row, len(list_repos(org_id)))


def set_scan_status(org_id: str, status: str, detail: str | None = None,
                    stamp_last: bool = False) -> None:
    conn = get_conn()
    try:
        if stamp_last:
            conn.execute("UPDATE orgs SET scan_status=?, scan_detail=?, last_scan_at=? WHERE id=?",
                         (status, detail, now(), org_id))
        else:
            conn.execute("UPDATE orgs SET scan_status=?, scan_detail=? WHERE id=?",
                         (status, detail, org_id))
        conn.commit()
    finally:
        conn.close()


# ── repos ─────────────────────────────────────────────────────────────────────

def add_repo(org_id: str, *, name: str, clone_url: str, full_name: str | None = None,
             default_branch: str | None = None, private: bool = False,
             source: str = "url") -> dict:
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM org_repos WHERE org_id=? AND clone_url=?",
            (org_id, clone_url)).fetchone()
        if existing:
            return {"id": existing["id"], "duplicate": True}
        repo_id = new_id("repo")
        conn.execute(
            "INSERT INTO org_repos(id, org_id, name, clone_url, full_name, default_branch,"
            " private, source, added_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (repo_id, org_id, name, clone_url, full_name, default_branch,
             1 if private else 0, source, now()))
        conn.commit()
    finally:
        conn.close()
    return {"id": repo_id, "duplicate": False}


def list_repos(org_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, org_id, name, clone_url, full_name, default_branch, private,"
            " source, status, detail, added_at FROM org_repos WHERE org_id=? ORDER BY name",
            (org_id,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def set_repo_status(repo_id: str, status: str, detail: str | None = None) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE org_repos SET status=?, detail=? WHERE id=?",
                     (status, detail, repo_id))
        conn.commit()
    finally:
        conn.close()


def delete_repo(org_id: str, repo_id: str) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM org_repos WHERE id=? AND org_id=?", (repo_id, org_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
