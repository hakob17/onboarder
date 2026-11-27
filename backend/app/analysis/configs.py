"""Config & contract harvest for the cross-project linker.

Lightweight, dependency-free scans: env-style assignments, compose service
names, and properties/yaml URL values. Used to resolve outbound URL templates
to internal hosts.
"""

import re
from pathlib import Path

ENV_RE = re.compile(r'^\s*([A-Z][A-Z0-9_]*)\s*[=:]\s*["\']?([^"\'#\n]+)', re.M)
COMPOSE_SERVICE_RE = re.compile(r"^  ([A-Za-z0-9][\w-]*):\s*$", re.M)
CONFIG_FILES = ("application.yml", "application.yaml", "application.properties", "config.yml")
MAX_READ = 256 * 1024


def _read(path: Path) -> str:
    try:
        return path.read_text("utf-8", errors="replace")[:MAX_READ]
    except OSError:
        return ""


def harvest(src_root: Path) -> dict:
    """→ {env: {VAR: value}, services: set[str]} for one project root."""
    env: dict[str, str] = {}
    services: set[str] = set()
    if not src_root.exists():
        return {"env": env, "services": services}
    from .languages import walk_files
    for path in walk_files(src_root, max_depth=4):
        if not path.is_file():
            continue
        name = path.name.lower()
        if len(path.relative_to(src_root).parts) > 4:
            continue
        if name.startswith(".env") or name in CONFIG_FILES:
            for key, value in ENV_RE.findall(_read(path)):
                env.setdefault(key.strip(), value.strip())
        elif name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            text = _read(path)
            in_services = False
            for line in text.splitlines():
                if re.match(r"^services:\s*$", line):
                    in_services = True
                    continue
                if in_services:
                    if line and not line.startswith(" "):
                        in_services = False
                        continue
                    m = re.match(r"^  ([A-Za-z0-9][\w-]*):\s*$", line)
                    if m:
                        services.add(m.group(1))
    return {"env": env, "services": services}


VAR_PATTERNS = (
    re.compile(r"\$\{?process\.env\.([A-Z][A-Z0-9_]*)\}?"),
    re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}"),
    re.compile(r"os\.environ(?:\.get)?[\[(]['\"]([A-Z][A-Z0-9_]*)['\"][)\]]"),
)


def resolve_template(template: str, env: dict[str, str]) -> str:
    """Substitute known env vars into a URL template."""
    out = template
    for pattern in VAR_PATTERNS:
        for var in pattern.findall(out):
            if var in env:
                out = pattern.sub(lambda m: env[m.group(1)] if m.group(1) == var else m.group(0), out, count=1)
    return out


def split_url(url: str) -> tuple[str | None, str]:
    """→ (host, path). Host is None for relative templates."""
    m = re.match(r"https?://([^/\s]+)(/.*)?$", url)
    if m:
        return m.group(1).split(":")[0], m.group(2) or "/"
    return None, url if url.startswith("/") else "/" + url


def norm_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_path(path: str) -> str:
    """Normalize path templates: /api/orders/{id} == /api/orders/:id == /api/orders/${x}."""
    parts = [p for p in path.split("?")[0].split("/") if p]
    out = []
    for p in parts:
        if p.startswith((":", "{", "<", "$")) or "${" in p or re.fullmatch(r"\d+", p):
            out.append("{}")
        else:
            out.append(p.lower())
    return "/" + "/".join(out)


# Segments a gateway / API convention adds that aren't the resource itself, so a mobile call
# routed through a gateway can still be matched to the backend endpoint it ultimately hits.
_GATEWAY_SEGS = {"api", "rest", "gateway", "gw", "public", "internal", "external", "app",
                 "backend", "bff", "services", "service", "web", "mobile", "v"}
_ACTION_SEGS = {"list", "all", "get", "fetch", "create", "add", "new", "update", "edit",
                "delete", "remove", "search", "query", "find", "detail", "details", "info"}
_VER_RE = re.compile(r"^v\d+$")


def resource_key(norm_path_value: str) -> str:
    """Reduce a normalized path to its resource tokens — drop api/version/gateway and
    action words, singularise plurals — so '/gw/order-service/v2/orders' and '/api/orders'
    both key to 'order'. Used as a looser, lower-confidence fallback match."""
    segs = []
    for s in norm_path_value.split("/"):
        if not s or s == "{}" or s in _GATEWAY_SEGS or s in _ACTION_SEGS or _VER_RE.match(s):
            continue
        if s.endswith("-service") or s.endswith("-svc"):
            s = s.rsplit("-", 1)[0]
        if len(s) > 3 and s.endswith("s"):
            s = s[:-1]  # orders -> order
        segs.append(s)
    return "/".join(segs)
