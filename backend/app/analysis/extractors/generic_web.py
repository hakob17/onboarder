"""Tier B+ generic web extractor.

Deterministic extraction for stacks without a deep (Tier A) extractor:
route registrations, SQL strings, and HTTP-client calls across JS/TS
(Express + NestJS decorators), Python (FastAPI/Flask decorators), Go
(gin/echo/net-http), and Retrofit interfaces (Java/Kotlin, mobile outbound).
Produces file-level logic nodes; every edge carries file:line evidence.
"""

import re

from ..languages import node_text
from ..sql_analysis import tables_in_sql

JS_LANGS = {"javascript", "typescript", "tsx"}
ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "all"}
JS_HTTP_RECEIVERS = {"axios", "fetch", "http", "https", "got", "request", "client", "api", "superagent", "ky"}
PY_HTTP_RECEIVERS = {"requests", "httpx", "session", "client", "aiohttp"}
GO_ROUTE_FIELDS = {"GET", "POST", "PUT", "DELETE", "PATCH"}
RETROFIT_ANNS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}
KT_RETROFIT_RE = re.compile(r'^\s*@(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"\s*\)')
FLASK_METHODS_RE = re.compile(r'methods\s*=\s*\[([^\]]*)\]')


def _walk(root):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def _named_args(call):
    args = call.child_by_field_name("arguments")
    if args is None:
        return []
    return [c for c in args.children if c.is_named]


def _string_value(node, source) -> str | None:
    if node is None:
        return None
    if node.type in ("string", "template_string", "interpreted_string_literal", "string_literal", "raw_string_literal"):
        return node_text(node, source).strip("\"'`")
    return None


def _enclosing(node, types: tuple):
    cur = node.parent
    while cur is not None:
        if cur.type in types:
            return cur
        cur = cur.parent
    return None


def _extract_js(pf):
    routes, outbound = [], []
    src = pf.source
    nest_classes: dict[int, dict] = {}  # class node id -> {name, base}

    for node in _walk(pf.tree.root_node):
        if node.type == "decorator":
            call = next((c for c in node.children if c.type == "call_expression"), None)
            if call is None:
                continue
            fn = call.child_by_field_name("function")
            if fn is None or fn.type != "identifier":
                continue
            dec = node_text(fn, src)
            arg_nodes = _named_args(call)
            arg = _string_value(arg_nodes[0] if arg_nodes else None, src) or ""
            cls = _enclosing(node, ("class_declaration",))
            if dec == "Controller" and cls is not None:
                name_node = cls.child_by_field_name("name")
                nest_classes[cls.id] = {
                    "name": node_text(name_node, src) if name_node else "controller",
                    "base": arg,
                }
            elif dec.upper() in RETROFIT_ANNS and cls is not None:
                info = nest_classes.setdefault(cls.id, {"name": "controller", "base": ""})
                routes.append({
                    "method": dec.upper(),
                    "path": "/" + "/".join(p for p in f"{info['base']}/{arg}".split("/") if p) or "/",
                    "handler": info["name"],
                    "line": node.start_point[0] + 1,
                    "layer": "controller",
                })
        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is None:
                continue
            arg_nodes = _named_args(node)
            first = arg_nodes[0] if arg_nodes else None
            raw = _string_value(first, src)
            line = node.start_point[0] + 1
            if fn.type == "member_expression":
                obj = fn.child_by_field_name("object")
                prop = fn.child_by_field_name("property")
                obj_name = node_text(obj, src).split(".")[-1] if obj is not None else ""
                meth = node_text(prop, src) if prop is not None else ""
                if raw is None or not meth:
                    continue
                is_urlish = raw.startswith(("http://", "https://")) or "${" in raw
                second_is_handler = len(arg_nodes) > 1 and arg_nodes[1].type in (
                    "arrow_function", "function_expression", "function", "identifier", "member_expression")
                if (meth.lower() in ROUTE_METHODS and raw.startswith("/")
                        and obj_name not in JS_HTTP_RECEIVERS and second_is_handler):
                    routes.append({
                        "method": "ANY" if meth.lower() == "all" else meth.upper(),
                        "path": raw, "handler": None, "line": line, "layer": "module",
                    })
                elif meth.lower() in ROUTE_METHODS | {"request"} and (is_urlish or obj_name in JS_HTTP_RECEIVERS):
                    outbound.append({
                        "method": meth.upper() if meth.lower() != "request" else "ANY",
                        "url": raw, "line": line, "client": obj_name or "http",
                    })
            elif fn.type == "identifier" and node_text(fn, src) == "fetch" and raw:
                outbound.append({"method": "ANY", "url": raw, "line": line, "client": "fetch"})
    return routes, outbound


def _extract_py(pf):
    routes, outbound = [], []
    src = pf.source
    for node in _walk(pf.tree.root_node):
        if node.type == "decorator":
            call = next((c for c in node.children if c.type == "call"), None)
            if call is None:
                continue
            fn = call.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            attr = fn.child_by_field_name("attribute")
            meth = node_text(attr, src) if attr is not None else ""
            arg_nodes = _named_args(call)
            path = _string_value(arg_nodes[0] if arg_nodes else None, src)
            if path is None or not path.startswith("/"):
                continue
            handler = None
            parent = node.parent
            if parent is not None and parent.type == "decorated_definition":
                fdef = next((c for c in parent.children if c.type == "function_definition"), None)
                if fdef is not None:
                    name = fdef.child_by_field_name("name")
                    handler = node_text(name, src) if name is not None else None
            if meth.lower() in ROUTE_METHODS:
                routes.append({"method": meth.upper(), "path": path, "handler": handler,
                               "line": node.start_point[0] + 1, "layer": "module"})
            elif meth.lower() == "route":
                args_text = node_text(call, src)
                m = FLASK_METHODS_RE.search(args_text)
                methods = re.findall(r'["\'](\w+)["\']', m.group(1)) if m else ["GET"]
                for http in methods:
                    routes.append({"method": http.upper(), "path": path, "handler": handler,
                                   "line": node.start_point[0] + 1, "layer": "module"})
        elif node.type == "call":
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "attribute":
                continue
            obj = fn.child_by_field_name("object")
            attr = fn.child_by_field_name("attribute")
            obj_name = node_text(obj, src).split(".")[-1] if obj is not None else ""
            meth = node_text(attr, src) if attr is not None else ""
            if obj_name not in PY_HTTP_RECEIVERS or meth.lower() not in ROUTE_METHODS:
                continue
            arg_nodes = _named_args(node)
            url = _string_value(arg_nodes[0] if arg_nodes else None, src)
            if url:
                outbound.append({"method": meth.upper(), "url": url,
                                 "line": node.start_point[0] + 1, "client": obj_name})
    return routes, outbound


def _extract_go(pf):
    routes, outbound = [], []
    src = pf.source
    for node in _walk(pf.tree.root_node):
        if node.type != "call_expression":
            continue
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "selector_expression":
            continue
        operand = fn.child_by_field_name("operand")
        field = fn.child_by_field_name("field")
        obj_name = node_text(operand, src).split(".")[-1] if operand is not None else ""
        meth = node_text(field, src) if field is not None else ""
        arg_nodes = _named_args(node)
        raw = _string_value(arg_nodes[0] if arg_nodes else None, src)
        if raw is None:
            continue
        line = node.start_point[0] + 1
        if meth in GO_ROUTE_FIELDS and raw.startswith("/"):
            routes.append({"method": meth, "path": raw, "handler": None, "line": line, "layer": "module"})
        elif meth in ("Handle", "HandleFunc") and raw.startswith("/"):
            routes.append({"method": "ANY", "path": raw, "handler": None, "line": line, "layer": "module"})
        elif obj_name == "http" and meth in ("Get", "Post", "Head") and raw.startswith(("http://", "https://")):
            outbound.append({"method": meth.upper(), "url": raw, "line": line, "client": "net/http"})
    return routes, outbound


def _extract_java_retrofit(pf):
    from .spring import parse_java_file
    outbound = []
    for cls in parse_java_file(pf.path, pf.tree, pf.source):
        if cls.kind != "interface":
            continue
        for method in cls.methods:
            for ann_name, ann_args, ann_line in method.annotations:
                if ann_name in RETROFIT_ANNS:
                    m = re.search(r'"([^"]*)"', ann_args or "")
                    outbound.append({
                        "method": ann_name,
                        "url": (m.group(1) if m else "/"),
                        "line": ann_line,
                        "client": "retrofit",
                    })
    return [], outbound


def _extract_kotlin(pf):
    outbound = []
    for i, line in enumerate(pf.source.decode("utf-8", "replace").splitlines(), 1):
        m = KT_RETROFIT_RE.match(line)
        if m:
            outbound.append({"method": m.group(1), "url": m.group(2), "line": i, "client": "retrofit"})
    return [], outbound


_DISPATCH = {
    "javascript": _extract_js, "typescript": _extract_js, "tsx": _extract_js,
    "python": _extract_py,
    "go": _extract_go,
    "java": _extract_java_retrofit,
    "kotlin": _extract_kotlin,
}


class GenericWebExtractor:
    name = "generic-web"

    def extract(self, project_id: str, generic, exclude_langs: set[str] | None = None):
        exclude = exclude_langs or set()
        nodes: dict[str, dict] = {}
        edges: dict[tuple, dict] = {}
        stats = {"endpoints": 0, "outbound": 0, "modules": 0, "sql_tables": 0}
        sources: dict[str, bytes] = {f.path: f.source for f in generic.files}

        def evidence(file: str, line: int) -> dict:
            lines = sources.get(file, b"").decode("utf-8", "replace").splitlines()
            snippet = lines[line - 1].strip()[:200] if 0 < line <= len(lines) else ""
            return {"file": file, "line": line, "snippet": snippet}

        def add_node(node_id: str, kind: str, name: str, qualified: str, file, line, metadata, conf=0.8):
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id, "kind": kind, "name": name, "qualified_name": qualified,
                    "file": file, "line_start": line, "line_end": line,
                    "metadata": {**metadata, "extractor": self.name}, "confidence": conf,
                }
            return node_id

        def add_edge(src: str, dst: str, kind: str, conf: float, ev: dict):
            key = (src, dst, kind)
            entry = edges.setdefault(key, {"src": src, "dst": dst, "kind": kind,
                                           "confidence": conf, "evidence": []})
            entry["confidence"] = max(entry["confidence"], conf)
            if ev not in entry["evidence"] and len(entry["evidence"]) < 20:
                entry["evidence"].append(ev)

        def module_node(pf, layer="module") -> str:
            stem = pf.path.split("/")[-1].rsplit(".", 1)[0]
            return add_node(
                f"{project_id}:logic:{pf.path}", "logic", stem, pf.path,
                pf.path, 1, {"layer": layer, "language": pf.language}, 0.85)

        for pf in generic.files:
            if pf.language in exclude:
                continue
            handler_fn = _DISPATCH.get(pf.language)
            if handler_fn is None:
                continue
            routes, outbound = handler_fn(pf)
            if not routes and not outbound:
                continue
            logic_id = module_node(pf)
            stats["modules"] += 1
            for r in routes:
                ep_name = f"{r['method']} {r['path']}"
                ep_id = add_node(
                    f"{project_id}:entry_point:{ep_name}", "entry_point", ep_name, ep_name,
                    pf.path, r["line"],
                    {"http_method": r["method"], "path": r["path"],
                     "handler": r.get("handler") or pf.path.split("/")[-1]}, 0.85)
                add_edge(ep_id, logic_id, "HANDLES", 0.85, evidence(pf.path, r["line"]))
                stats["endpoints"] += 1
            for o in outbound:
                out_name = f"{o['method']} {o['url']}"
                out_id = add_node(
                    f"{project_id}:outbound_call:{out_name}", "outbound_call", out_name, out_name,
                    pf.path, o["line"],
                    {"http_method": o["method"], "url_template": o["url"], "client": o["client"]},
                    0.9 if o["client"] == "retrofit" else 0.75)
                add_edge(logic_id, out_id, "MAKES_CALL",
                         0.9 if o["client"] == "retrofit" else 0.75, evidence(pf.path, o["line"]))
                stats["outbound"] += 1

        by_file = {f.path: f for f in generic.files}
        for cand in generic.candidates:
            if cand["kind"] != "sql":
                continue
            pf = by_file.get(cand["file"])
            if pf is None or pf.language in exclude:
                continue
            pairs = tables_in_sql(cand["value"])
            if not pairs:
                continue
            logic_id = module_node(pf)
            for table, op in pairs:
                t_id = add_node(f"{project_id}:table:{table}", "table", table, table,
                                cand["file"], cand["line"], {"source": "sql", "columns": []}, 0.75)
                add_edge(logic_id, t_id, op + "S", 0.75, evidence(cand["file"], cand["line"]))
                stats["sql_tables"] += 1

        return list(nodes.values()), list(edges.values()), stats
