"""Minimal GitHub connector: enumerate an org's (or user's) repositories so the
owner can connect them in one click. Standard-library only — no extra deps in the
hosted image.

The token is used transiently (to list, and later to clone private repos) and is
never stored, never logged, and never echoed back in any API response.
"""
import json
import urllib.error
import urllib.request

_API = "https://api.github.com"
_UA = "onboarder-cloud"  # generic client name — never the user's identity


class GitHubError(RuntimeError):
    pass


def _get(path: str, token: str | None) -> tuple[int, object, dict]:
    req = urllib.request.Request(_API + path, method="GET")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", _UA)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8") or "null")
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        # Surface a clean message; never include the token.
        try:
            msg = json.loads(e.read().decode("utf-8")).get("message", e.reason)
        except Exception:
            msg = e.reason
        raise GitHubError(f"GitHub {e.code}: {msg}") from None
    except urllib.error.URLError as e:
        raise GitHubError(f"Could not reach GitHub: {e.reason}") from None


def _collect(owner_path: str, token: str | None, limit: int) -> list[dict]:
    out: list[dict] = []
    page = 1
    while len(out) < limit and page <= 10:
        status, body, _ = _get(f"{owner_path}?per_page=100&page={page}&sort=updated", token)
        if not isinstance(body, list) or not body:
            break
        out.extend(body)
        if len(body) < 100:
            break
        page += 1
    return out[:limit]


def list_repos(owner: str, token: str | None = None, limit: int = 200) -> list[dict]:
    """List repositories for a GitHub org or user. Tries the org endpoint first
    (sees private repos when the token allows), then falls back to the user
    endpoint. Returns a trimmed, secret-free shape."""
    owner = owner.strip().strip("/")
    if not owner or "/" in owner:
        raise GitHubError("Enter a GitHub organization or user name, e.g. 'vercel'.")
    repos: list[dict] = []
    try:
        repos = _collect(f"/orgs/{owner}/repos", token, limit)
    except GitHubError:
        repos = []
    if not repos:
        repos = _collect(f"/users/{owner}/repos", token, limit)
    result = []
    for r in repos:
        if r.get("archived") or r.get("disabled"):
            continue
        result.append({
            "name": r["name"],
            "full_name": r["full_name"],
            "clone_url": r["clone_url"],          # https URL, no token
            "default_branch": r.get("default_branch") or "main",
            "private": bool(r.get("private")),
            "description": r.get("description"),
            "language": r.get("language"),
        })
    return result
