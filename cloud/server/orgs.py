"""Org-space API: create an org, connect repositories (by URL or from a GitHub
org/user), kick off a scan, and expose the read-only directory a viewer browses.

Mutating actions (connect repos, scan, delete) require the org's owner key, sent
as the ``x-owner-key`` header. Reading the directory and entering a space is open
to any viewer — that is the "walk into the org space" experience.
"""
import ipaddress
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import github, orgdb, scan

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_owner(org_id: str, key: str | None) -> dict:
    org = orgdb.get_org(org_id)
    if not org:
        raise HTTPException(404, "org not found")
    if not orgdb.verify_owner_key(org_id, key):
        raise HTTPException(403, "invalid or missing owner key")
    return org


_PRIVATE_HOST = re.compile(r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.)")


def _valid_clone_url(url: str) -> str:
    """Only allow public https git URLs — blocks SSRF to internal addresses."""
    url = url.strip()
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        raise HTTPException(400, "clone URL must be an https:// git URL")
    host = p.hostname.lower()
    if _PRIVATE_HOST.match(host) or host.endswith((".internal", ".local", ".localhost")):
        raise HTTPException(400, "internal hosts are not allowed")
    try:  # literal IPs that fall in private/loopback/link-local ranges
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, "internal addresses are not allowed")
    except ValueError:
        pass  # a hostname, not an IP — fine
    return url


def _repo_name_from_url(url: str) -> str:
    tail = urlparse(url).path.rstrip("/").split("/")[-1]
    return re.sub(r"\.git$", "", tail) or "repo"


# ── models ────────────────────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    name: str
    blurb: str | None = None


class RepoAdd(BaseModel):
    clone_url: str
    name: str | None = None


class GitHubList(BaseModel):
    owner: str
    token: str | None = None


class GitHubImport(BaseModel):
    owner: str
    token: str | None = None
    full_names: list[str] | None = None  # subset to add; None = add all returned


class ScanReq(BaseModel):
    token: str | None = None  # transient; only needed for private repos


# ── org directory (public) ────────────────────────────────────────────────────

@router.post("")
def create_org(body: OrgCreate) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name is required")
    # returns the owner_key exactly once — the caller must save it
    return orgdb.create_org(name, body.blurb)


@router.get("")
def list_orgs() -> list[dict]:
    return orgdb.list_orgs()


@router.get("/{org_id}")
def get_org(org_id: str) -> dict:
    org = orgdb.public_org(org_id)
    if not org:
        raise HTTPException(404, "org not found")
    org["repos"] = orgdb.list_repos(org_id)
    return org


# ── connect repositories (owner) ──────────────────────────────────────────────

@router.post("/{org_id}/repos")
def add_repo(org_id: str, body: RepoAdd, x_owner_key: str | None = Header(None)) -> dict:
    _require_owner(org_id, x_owner_key)
    url = _valid_clone_url(body.clone_url)
    name = (body.name or _repo_name_from_url(url)).strip()
    res = orgdb.add_repo(org_id, name=name, clone_url=url, full_name=None,
                         private=False, source="url")
    return {"ok": True, **res}


@router.post("/{org_id}/github/list")
def github_list(org_id: str, body: GitHubList, x_owner_key: str | None = Header(None)) -> dict:
    _require_owner(org_id, x_owner_key)
    try:
        repos = github.list_repos(body.owner, body.token)
    except github.GitHubError as e:
        raise HTTPException(400, str(e)) from None
    return {"owner": body.owner, "count": len(repos), "repos": repos}


@router.post("/{org_id}/github/import")
def github_import(org_id: str, body: GitHubImport, x_owner_key: str | None = Header(None)) -> dict:
    _require_owner(org_id, x_owner_key)
    try:
        repos = github.list_repos(body.owner, body.token)
    except github.GitHubError as e:
        raise HTTPException(400, str(e)) from None
    wanted = set(body.full_names) if body.full_names else None
    added = 0
    for r in repos:
        if wanted is not None and r["full_name"] not in wanted:
            continue
        res = orgdb.add_repo(org_id, name=r["name"], clone_url=r["clone_url"],
                             full_name=r["full_name"], default_branch=r["default_branch"],
                             private=r["private"], source="github")
        if not res.get("duplicate"):
            added += 1
    return {"ok": True, "added": added, "total": len(repos)}


@router.delete("/{org_id}/repos/{repo_id}")
def delete_repo(org_id: str, repo_id: str, x_owner_key: str | None = Header(None)) -> dict:
    _require_owner(org_id, x_owner_key)
    if not orgdb.delete_repo(org_id, repo_id):
        raise HTTPException(404, "repo not found")
    return {"ok": True}


# ── scan (owner) ──────────────────────────────────────────────────────────────

@router.post("/{org_id}/scan")
def scan_now(org_id: str, body: ScanReq, x_owner_key: str | None = Header(None)) -> dict:
    org = _require_owner(org_id, x_owner_key)
    if org["scan_status"] == "scanning":
        raise HTTPException(409, "a scan is already running")
    if not orgdb.list_repos(org_id):
        raise HTTPException(400, "connect at least one repository first")
    scan.scan_org_async(org_id, body.token)
    return {"ok": True, "scan_status": "scanning"}
