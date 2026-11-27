"""Apollo Federation extractor (schema-first SDL).

Reads a subgraph's `.graphql` / `.graphqls` / `.gql` schema files (and inline
`gql` tagged templates) and turns them into graph nodes:

- root operations (Query / Mutation / Subscription fields) -> `entry_point` nodes,
  so a subgraph's GraphQL API surface shows up like REST endpoints.
- federated object types (`@key`) -> `graphql_entity` nodes, tagged as OWNED by the
  subgraph that declares real fields, or REFERENCED by a subgraph that only extends /
  re-declares it with `@external` fields.

The cross-project linker then wires a reference in one subgraph to the owner in
another (kind `GRAPHQL_ENTITY`) — that edge is the federation topology.
"""
import re

from ..languages import walk_files

SDL_EXTS = {".graphql", ".graphqls", ".gql"}
MAX_SDL_FILES = 400
MAX_SDL_BYTES = 512 * 1024
_ROOT_TYPES = {"Query": "query", "Mutation": "mutation", "Subscription": "subscription"}

# `type X @key(...) {`  /  `extend type X @key(...) {`
_TYPE_RE = re.compile(r'(?:^|\n)\s*(extend\s+)?(?:type|interface)\s+([A-Za-z_]\w*)([^\{]*)\{')
_KEY_RE = re.compile(r'@key\s*\(\s*fields\s*:\s*"([^"]*)"')
# gql`...` / graphql`...` tagged templates in JS/TS
_GQL_TAG_RE = re.compile(r'(?:gql|graphql)\s*`([^`]*)`', re.S)
# a field line inside a type body: name(args?): Type directives?
_FIELD_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:\s*([\[\]\w!]+)([^\n]*)$', re.M)


def _brace_body(text: str, brace_idx: int) -> str:
    depth = 0
    for j in range(brace_idx, len(text)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[brace_idx + 1:j]
    return text[brace_idx + 1:]


def _scan_sdl(text: str):
    """-> (entities: {name: {owner, ref, key}}, operations: [(optype, field, ret_type)])."""
    entities: dict[str, dict] = {}
    operations: list[tuple[str, str, str]] = []
    for m in _TYPE_RE.finditer(text):
        is_extend = bool(m.group(1))
        name = m.group(2)
        directives = m.group(3) or ""
        body = _brace_body(text, m.end() - 1)
        if name in _ROOT_TYPES:
            optype = _ROOT_TYPES[name]
            for fm in _FIELD_RE.finditer(body):
                ret = fm.group(2).strip("[]!")
                operations.append((optype, fm.group(1), ret))
            continue
        key = _KEY_RE.search(directives)
        if not key and not is_extend:
            continue  # a plain object type, not a federated entity
        fields = list(_FIELD_RE.finditer(body))
        external = sum(1 for fm in fields if "@external" in (fm.group(3) or ""))
        real = sum(1 for fm in fields if "@external" not in (fm.group(3) or ""))
        ent = entities.setdefault(name, {"owner": False, "ref": False,
                                         "key": key.group(1) if key else None})
        # owns it if it contributes real (non-external) fields and isn't a bare extend stub
        if not is_extend and real > 0:
            ent["owner"] = True
        # references it if it only extends / re-declares with @external key fields
        if is_extend or (external > 0 and real == 0):
            ent["ref"] = True
        if key and not ent["key"]:
            ent["key"] = key.group(1)
    return entities, operations


class GraphQLFederationExtractor:
    name = "graphql-federation"

    def extract(self, project_id: str, src_root):
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        entities: dict[str, dict] = {}   # name -> {owner, ref, key, file, line}
        operations: dict[tuple, dict] = {}
        stats = {"sdl_files": 0, "operations": 0, "owned_entities": 0, "referenced_entities": 0}

        def record(text: str, rel: str):
            ents, ops = _scan_sdl(text)
            for name, info in ents.items():
                e = entities.setdefault(name, {"owner": False, "ref": False,
                                               "key": info["key"], "file": rel})
                e["owner"] = e["owner"] or info["owner"]
                e["ref"] = e["ref"] or info["ref"]
                e["key"] = e["key"] or info["key"]
            for optype, field, ret in ops:
                operations[(optype, field)] = {"ret": ret, "file": rel}

        count = 0
        for path in walk_files(src_root):
            ext = path.suffix.lower()
            rel = str(path.relative_to(src_root))
            try:
                if ext in SDL_EXTS:
                    text = path.read_text("utf-8", errors="replace")
                    if len(text) > MAX_SDL_BYTES:
                        continue
                    record(text, rel)
                    stats["sdl_files"] += 1
                    count += 1
                elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
                    text = path.read_text("utf-8", errors="replace")
                    if "gql`" not in text and "graphql`" not in text:
                        continue
                    for tag in _GQL_TAG_RE.findall(text):
                        if "type " in tag or "extend " in tag:
                            record(tag, rel)
            except OSError:
                continue
            if count > MAX_SDL_FILES:
                break

        if not entities and not operations:
            return [], [], {}

        # federated entity nodes (anchors for the cross-subgraph links)
        for name, info in entities.items():
            role = "owner" if info["owner"] and not info["ref"] else (
                "reference" if info["ref"] and not info["owner"] else "shared")
            nid = f"{project_id}:graphql_entity:{name}"
            nodes[nid] = {
                "id": nid, "kind": "graphql_entity", "name": name, "qualified_name": name,
                "file": info["file"], "line_start": 1, "line_end": 1,
                "metadata": {"federation_role": role, "owner": info["owner"],
                             "references": info["ref"], "key": info["key"],
                             "extractor": self.name},
                "confidence": 0.9,
            }
            if info["owner"]:
                stats["owned_entities"] += 1
            if info["ref"] and not info["owner"]:
                stats["referenced_entities"] += 1

        # operation (Query/Mutation/Subscription field) nodes -> entry points
        for (optype, field), info in operations.items():
            op_name = f"{optype} {field}"
            nid = f"{project_id}:entry_point:{op_name}"
            nodes[nid] = {
                "id": nid, "kind": "entry_point", "name": op_name, "qualified_name": op_name,
                "file": info["file"], "line_start": 1, "line_end": 1,
                "metadata": {"http_method": "POST", "path": f"/graphql#{optype}.{field}",
                             "graphql": True, "operation": optype, "returns": info["ret"],
                             "handler": "graphql", "extractor": self.name},
                "confidence": 0.85,
            }
            stats["operations"] += 1
            # if the operation returns a federated entity, wire it to that entity
            ent_id = f"{project_id}:graphql_entity:{info['ret']}"
            if ent_id in nodes:
                edges.append({"src": nid, "dst": ent_id, "kind": "RETURNS", "confidence": 0.7,
                              "evidence": [{"file": info["file"], "line": 1,
                                            "snippet": f"{op_name}: {info['ret']}"}]})

        return list(nodes.values()), edges, stats
