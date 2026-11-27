"""Client-surface extractor: gives frontends and mobile apps real nodes.

A web or mobile app is a CLIENT, not a server, so it has no HTTP endpoints — the
generic extractor finds nothing. But it does have a navigable surface:

- web (Vue / React / Angular): router routes and page components  -> `page` nodes
- android / mobile (Kotlin / Java): Activities, Fragments, @Composable screens -> `screen` nodes

and it calls the backend (axios / fetch inside .vue <script> blocks, which the
generic pass can't parse) -> `outbound_call` nodes, which the linker then wires to
the backend's endpoints. Pages/screens are a distinct kind so the linker never
mistakes them for real HTTP endpoints.
"""
import re

from ..languages import walk_files

PAGE_DIRS = {"pages", "views", "screens", "page", "view", "screen"}
PAGE_EXT = {".vue", ".jsx", ".tsx", ".svelte"}
_ROUTER_HINT = ("createRouter", "VueRouter", "createWebHistory", "createWebHashHistory",
                "react-router", "createBrowserRouter", "RouterModule", "useRoutes", "<Routes")
MAX_BYTES = 600 * 1024

_VUE_ROUTE_RE = re.compile(r"""\bpath\s*:\s*['"]([^'"]*)['"]""")
_REACT_ROUTE_RE = re.compile(r"""<Route\b[^>]*\bpath\s*=\s*['"]([^'"]+)['"]""")
_ANDROID_SCREEN_RE = re.compile(
    r"\bclass\s+(\w+)\s*(?::|\bextends\b)[^\{(]*\b"
    r"(AppCompatActivity|ComponentActivity|Activity|DialogFragment|BottomSheetDialogFragment|Fragment)\b")
_COMPOSABLE_SCREEN_RE = re.compile(r"@Composable\b[^\n]*\n\s*(?:private\s+|internal\s+|public\s+)?fun\s+(\w*(?:Screen|Page))\b")
_API_CALL_RE = re.compile(
    r"""\b(axios|fetch|\$http|http|api|client|useFetch|useAxios|\$fetch)\s*"""
    r"""(?:\.\s*(get|post|put|delete|patch|request))?\s*\(\s*[`'"]([^`'"\s)]+)""")
_HTTP_VERB_DEFAULT = "ANY"


class ClientSurfaceExtractor:
    name = "client-surface"

    def extract(self, project_id: str, src_root):
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        stats = {"pages": 0, "screens": 0, "client_calls": 0}

        def add(nid, kind, name, file, line, meta, conf=0.75):
            if nid not in nodes:
                nodes[nid] = {"id": nid, "kind": kind, "name": name, "qualified_name": name,
                              "file": file, "line_start": line, "line_end": line,
                              "metadata": {**meta, "extractor": self.name}, "confidence": conf}
            return nid

        def page(name, file, line, path=None):
            nid = f"{project_id}:page:{name}"
            if nid not in nodes:
                stats["pages"] += 1
            add(nid, "page", name, file, line,
                {"http_method": "PAGE", "path": path or name, "surface": "page"})

        def screen(name, file, line):
            nid = f"{project_id}:screen:{name}"
            if nid not in nodes:
                stats["screens"] += 1
            add(nid, "screen", name, file, line, {"http_method": "SCREEN", "path": name, "surface": "screen"})

        n = 0
        for p in walk_files(src_root):
            ext = p.suffix.lower()
            if ext not in {".js", ".ts", ".jsx", ".tsx", ".vue", ".svelte", ".kt", ".java"}:
                continue
            n += 1
            if n > 40000:
                break
            rel = str(p.relative_to(src_root))
            dir_parts = {part.lower() for part in p.parts[:-1]}
            try:
                text = p.read_text("utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > MAX_BYTES:
                continue

            if ext in {".js", ".ts", ".jsx", ".tsx", ".vue"}:
                # router-defined routes (Vue / React)
                if any(h in text for h in _ROUTER_HINT) or "router" in p.stem.lower():
                    for m in _VUE_ROUTE_RE.finditer(text):
                        path = m.group(1)
                        if path.startswith("/") or path == "":
                            page(path or "/", rel, text.count("\n", 0, m.start()) + 1, path or "/")
                    for m in _REACT_ROUTE_RE.finditer(text):
                        page(m.group(1), rel, text.count("\n", 0, m.start()) + 1, m.group(1))

            # page component by directory convention (Dashboard.vue under pages/ or views/)
            if ext in PAGE_EXT and (dir_parts & PAGE_DIRS):
                page(p.stem, rel, 1)

            # android screens
            if ext in {".kt", ".java"}:
                for m in _ANDROID_SCREEN_RE.finditer(text):
                    screen(m.group(1), rel, text.count("\n", 0, m.start()) + 1)
                for m in _COMPOSABLE_SCREEN_RE.finditer(text):
                    screen(m.group(1), rel, text.count("\n", 0, m.start()) + 1)

            # API calls inside .vue/.svelte (the generic pass can't parse these files)
            if ext in {".vue", ".svelte"}:
                for m in _API_CALL_RE.finditer(text):
                    verb = (m.group(2) or _HTTP_VERB_DEFAULT).upper()
                    url = m.group(3)
                    if not url or url in ("/", "#") or len(url) > 300:
                        continue
                    name = f"{verb} {url}"
                    nid = f"{project_id}:outbound_call:{name}"
                    if nid not in nodes:
                        stats["client_calls"] += 1
                    add(nid, "outbound_call", name, rel, text.count("\n", 0, m.start()) + 1,
                        {"http_method": verb, "url_template": url, "client": m.group(1)}, 0.6)

        return list(nodes.values()), edges, stats
