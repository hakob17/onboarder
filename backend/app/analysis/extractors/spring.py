import re
from dataclasses import dataclass, field

from ..languages import node_text

MAPPING_ANNOTATIONS = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "DeleteMapping": "DELETE", "PatchMapping": "PATCH", "RequestMapping": None,
}
REPO_BASE_RE = re.compile(
    r"\b(?:JpaRepository|CrudRepository|PagingAndSortingRepository|ListCrudRepository|"
    r"ListPagingAndSortingRepository|MongoRepository|ReactiveCrudRepository)\s*<\s*(\w+)"
)
READ_PREFIXES = ("find", "read", "get", "query", "search", "stream", "count", "exists")
WRITE_PREFIXES = ("save", "insert", "update", "delete", "remove", "merge", "upsert", "persist")
HTTP_CLIENT_TYPES = {"RestTemplate", "WebClient", "RestClient", "TestRestTemplate"}
# Message-consumer annotations → (trigger, destination node kind). Each annotated
# method becomes an entry_point (like an HTTP endpoint) triggered by a topic/queue.
LISTENER_ANNOTATIONS = {
    "KafkaListener": ("kafka", "topic"),
    "KafkaHandler": ("kafka", "topic"),
    "RabbitListener": ("rabbitmq", "queue"),
    "JmsListener": ("jms", "queue"),
    "SqsListener": ("sqs", "queue"),
    "StreamListener": ("stream", "topic"),
    "EventListener": ("event", None),
    "TransactionalEventListener": ("event", None),
}
# Producer templates → (trigger, destination node kind); a send() makes a PRODUCES edge.
MESSAGING_TEMPLATE_TYPES = {
    "KafkaTemplate": ("kafka", "topic"),
    "RabbitTemplate": ("rabbitmq", "queue"),
    "AmqpTemplate": ("rabbitmq", "queue"),
    "JmsTemplate": ("jms", "queue"),
    "StreamBridge": ("stream", "topic"),
}
SEND_METHODS = {"send", "sendDefault", "convertAndSend", "convertSendAndReceive", "sendAndReceive"}
LISTENER_DEST_RE = re.compile(r'(?:topics|queues|destination|value|topicPattern)\s*=\s*"([^"]+)"')
REST_CALL_METHODS = {
    "getForObject": "GET", "getForEntity": "GET", "postForObject": "POST",
    "postForEntity": "POST", "postForLocation": "POST", "put": "PUT",
    "delete": "DELETE", "patchForObject": "PATCH", "exchange": "CALL", "uri": "CALL",
}
FIRST_STRING_RE = re.compile(r'"([^"]*)"')
RM_METHOD_RE = re.compile(r"RequestMethod\.(\w+)")
JAVA_TO_SQL = {
    "Long": "bigint", "long": "bigint", "Integer": "int", "int": "int",
    "Short": "smallint", "short": "smallint", "String": "varchar",
    "Boolean": "bool", "boolean": "bool", "Instant": "timestamptz",
    "LocalDateTime": "timestamp", "LocalDate": "date", "OffsetDateTime": "timestamptz",
    "BigDecimal": "numeric", "Double": "double", "double": "double",
    "Float": "real", "float": "real", "UUID": "uuid", "byte[]": "bytea",
}
COLLECTION_TYPES = {"List", "Set", "Map", "Collection"}
RELATION_ANNS = {"OneToMany", "ManyToMany"}
TO_ONE_ANNS = {"ManyToOne", "OneToOne"}


def _entity_columns(entity: "JavaClass") -> list[dict]:
    columns = []
    for name, jtype, anns, _line in entity.field_details:
        ann_names = {a[0] for a in anns}
        if "Transient" in ann_names or jtype in COLLECTION_TYPES or ann_names & RELATION_ANNS:
            continue
        col_ann = next((a for a in anns if a[0] in ("Column", "JoinColumn")), None)
        col_name = (_first_string(col_ann[1]) if col_ann else None)
        if ann_names & TO_ONE_ANNS:
            columns.append({"name": col_name or _snake(name) + "_id", "type": "bigint", "pk": False})
            continue
        columns.append({
            "name": col_name or _snake(name),
            "type": JAVA_TO_SQL.get(jtype, _snake(jtype)),
            "pk": "Id" in ann_names,
        })
    return columns


@dataclass
class JavaMethod:
    name: str
    line_start: int
    line_end: int
    annotations: list = field(default_factory=list)
    invocations: list = field(default_factory=list)


@dataclass
class JavaClass:
    name: str
    package: str
    kind: str  # class | interface
    file: str
    line_start: int
    line_end: int
    annotations: list = field(default_factory=list)
    extends_text: str = ""
    implements: list = field(default_factory=list)
    fields: dict = field(default_factory=dict)  # var name -> simple type
    field_details: list = field(default_factory=list)  # (name, type, ann_names, line)
    methods: list = field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.package}.{self.name}" if self.package else self.name

    def annotation_names(self) -> set:
        return {a[0] for a in self.annotations}

    def annotation(self, name: str):
        return next((a for a in self.annotations if a[0] == name), None)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _annotations_of(node, source) -> list:
    out = []
    mods = next((c for c in node.children if c.type == "modifiers"), None)
    if mods is None:
        return out
    for c in mods.children:
        if c.type in ("marker_annotation", "annotation"):
            name_node = c.child_by_field_name("name")
            args_node = c.child_by_field_name("arguments")
            name = node_text(name_node, source).split(".")[-1] if name_node else ""
            args = node_text(args_node, source) if args_node else ""
            out.append((name, args, c.start_point[0] + 1))
    return out


def _type_base(node, source) -> str:
    if node is None:
        return ""
    if node.type == "type_identifier":
        return node_text(node, source)
    if node.type == "scoped_type_identifier":
        return node_text(node, source).split(".")[-1]
    if node.type == "generic_type":
        for c in node.children:
            if c.type in ("type_identifier", "scoped_type_identifier"):
                return _type_base(c, source)
    if node.type == "array_type":
        return _type_base(node.child_by_field_name("element"), source)
    text = node_text(node, source)
    return text.split("<")[0].split(".")[-1].strip()


def _receiver_root(node, source) -> str | None:
    while node is not None and node.type == "method_invocation":
        node = node.child_by_field_name("object")
    if node is None:
        return None
    if node.type == "identifier":
        return node_text(node, source)
    if node.type == "field_access":
        parts = node_text(node, source).split(".")
        if parts and parts[0] == "this" and len(parts) > 1:
            return parts[1]
        return parts[0] if parts else None
    return None


def _collect_invocations(body, source) -> list:
    out = []
    if body is None:
        return out
    stack = [body]
    while stack:
        node = stack.pop()
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            obj_node = node.child_by_field_name("object")
            args_node = node.child_by_field_name("arguments")
            str_args = []
            if args_node is not None:
                for a in args_node.children:
                    if a.type == "string_literal":
                        str_args.append(node_text(a, source).strip('"'))
            out.append({
                "receiver": _receiver_root(obj_node, source),
                "name": node_text(name_node, source) if name_node else "",
                "line": node.start_point[0] + 1,
                "str_args": str_args,
            })
        stack.extend(node.children)
    return out


def parse_java_file(rel_path: str, tree, source: bytes) -> list[JavaClass]:
    classes: list[JavaClass] = []
    package = ""
    root = tree.root_node
    for child in root.children:
        if child.type == "package_declaration":
            for c in child.children:
                if c.type in ("scoped_identifier", "identifier"):
                    package = node_text(c, source)
    stack = list(root.children)
    while stack:
        node = stack.pop()
        if node.type not in ("class_declaration", "interface_declaration"):
            stack.extend(node.children)
            continue
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        jc = JavaClass(
            name=node_text(name_node, source),
            package=package,
            kind="interface" if node.type == "interface_declaration" else "class",
            file=rel_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            annotations=_annotations_of(node, source),
        )
        for c in node.children:
            if c.type == "superclass":
                jc.extends_text = node_text(c, source)
            elif c.type in ("super_interfaces", "extends_interfaces"):
                jc.extends_text += " " + node_text(c, source)
                for t in c.children:
                    if t.type == "type_list":
                        jc.implements.extend(
                            _type_base(x, source) for x in t.children if x.is_named
                        )
        body = node.child_by_field_name("body")
        if body is None:
            classes.append(jc)
            continue
        for member in body.children:
            if member.type == "field_declaration":
                type_node = member.child_by_field_name("type")
                base = _type_base(type_node, source)
                field_anns = _annotations_of(member, source)
                for d in member.children:
                    if d.type == "variable_declarator":
                        var = d.child_by_field_name("name")
                        if var is not None and base:
                            var_name = node_text(var, source)
                            jc.fields[var_name] = base
                            jc.field_details.append(
                                (var_name, base, field_anns, member.start_point[0] + 1))
            elif member.type == "constructor_declaration":
                params = member.child_by_field_name("parameters")
                if params is not None:
                    for p in params.children:
                        if p.type == "formal_parameter":
                            t = p.child_by_field_name("type")
                            n = p.child_by_field_name("name")
                            if t is not None and n is not None:
                                jc.fields.setdefault(node_text(n, source), _type_base(t, source))
                jc.methods.append(JavaMethod(
                    name="<init>",
                    line_start=member.start_point[0] + 1,
                    line_end=member.end_point[0] + 1,
                    invocations=_collect_invocations(member.child_by_field_name("body"), source),
                ))
            elif member.type == "method_declaration":
                m_name = member.child_by_field_name("name")
                jc.methods.append(JavaMethod(
                    name=node_text(m_name, source) if m_name else "",
                    line_start=member.start_point[0] + 1,
                    line_end=member.end_point[0] + 1,
                    annotations=_annotations_of(member, source),
                    invocations=_collect_invocations(member.child_by_field_name("body"), source),
                ))
        classes.append(jc)
    return classes


def _first_string(args: str) -> str | None:
    m = FIRST_STRING_RE.search(args or "")
    return m.group(1) if m else None


def _join_path(base: str, sub: str) -> str:
    base = (base or "").strip()
    sub = (sub or "").strip()
    joined = "/" + "/".join(p for p in (base.strip("/") + "/" + sub.strip("/")).split("/") if p)
    return joined or "/"


def _classify_repo_method(name: str) -> str | None:
    lowered = name.lower()
    if lowered.startswith(WRITE_PREFIXES):
        return "WRITE"
    if lowered.startswith(READ_PREFIXES):
        return "READ"
    return None


class _EdgeSet:
    def __init__(self):
        self._edges: dict[tuple, dict] = {}

    def add(self, src: str, dst: str, kind: str, confidence: float, evidence: dict):
        key = (src, dst, kind)
        entry = self._edges.setdefault(
            key, {"src": src, "dst": dst, "kind": kind, "confidence": confidence, "evidence": []}
        )
        entry["confidence"] = max(entry["confidence"], confidence)
        if evidence and evidence not in entry["evidence"] and len(entry["evidence"]) < 20:
            entry["evidence"].append(evidence)

    def all(self) -> list[dict]:
        return list(self._edges.values())


_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")


def _flatten_yaml(d: dict, prefix: str, out: dict) -> None:
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            _flatten_yaml(v, key, out)
        elif isinstance(v, (str, int, float, bool)):
            out[key] = str(v)


def _collect_spring_props(project_id: str) -> dict[str, str]:
    """Flat property map from application.{yml,yaml,properties} (+ profile variants)."""
    from ...config import resolve_root
    from ...db import get_conn
    conn = get_conn()
    try:
        row = conn.execute("SELECT root_path FROM projects WHERE id = ?", (project_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    try:
        root = resolve_root(row["root_path"])
    except Exception:
        return {}
    props: dict[str, str] = {}
    patterns = ("application.yml", "application.yaml", "application.properties",
                "application-*.yml", "application-*.yaml", "application-*.properties",
                "bootstrap.yml", "bootstrap.properties")
    seen = 0
    for pat in patterns:
        for path in sorted(root.rglob(pat)):
            if any(part in ("target", "build", "node_modules", ".git", ".gradle") for part in path.parts):
                continue
            seen += 1
            if seen > 30:
                break
            try:
                text = path.read_text("utf-8", errors="replace")
            except OSError:
                continue
            if path.suffix in (".yml", ".yaml"):
                import yaml
                try:
                    for doc in yaml.safe_load_all(text):
                        if isinstance(doc, dict):
                            _flatten_yaml(doc, "", props)
                except yaml.YAMLError:
                    continue
            else:
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "!")) and "=" in line:
                        k, _, v = line.partition("=")
                        props[k.strip()] = v.strip()
    return props


def _make_placeholder_resolver(project_id: str):
    """Return resolve(value) that expands Spring ${key[:default]} placeholders (relaxed binding)."""
    props = _collect_spring_props(project_id)
    norm = {re.sub(r"[-_]", "", k).lower(): v for k, v in props.items()}

    def resolve(value: str | None) -> str | None:
        if not value or "${" not in value:
            return value

        def sub(m: re.Match) -> str:
            inner = m.group(1)
            key, sep, default = inner.partition(":")
            key = key.strip()
            v = props.get(key)
            if v is None:
                v = norm.get(re.sub(r"[-_]", "", key).lower())
            if v is None:
                return default.strip() if sep else m.group(0)
            return str(v)

        return _PLACEHOLDER_RE.sub(sub, value)

    return resolve


class SpringExtractor:
    name = "spring"

    def matches(self, stack: str) -> bool:
        return stack in ("spring", "java")

    def extract(self, project_id: str, java_files: list) -> tuple[list[dict], list[dict]]:
        """java_files: list of (rel_path, tree, source_bytes)."""
        classes: list[JavaClass] = []
        sources: dict[str, bytes] = {}
        for rel_path, tree, source in java_files:
            sources[rel_path] = source
            classes.extend(parse_java_file(rel_path, tree, source))

        resolve_placeholder = _make_placeholder_resolver(project_id)

        def evidence(file: str, line: int) -> dict:
            src = sources.get(file)
            snippet = ""
            if src is not None:
                lines = src.decode("utf-8", "replace").splitlines()
                if 0 < line <= len(lines):
                    snippet = lines[line - 1].strip()[:200]
            return {"file": file, "line": line, "snippet": snippet}

        by_name: dict[str, list[JavaClass]] = {}
        for c in classes:
            by_name.setdefault(c.name, []).append(c)
        impls: dict[str, list[JavaClass]] = {}
        for c in classes:
            if c.kind == "class":
                for iface in c.implements:
                    impls.setdefault(iface, []).append(c)

        controllers, services, repos, entities, feigns = [], [], [], [], []
        for c in classes:
            anns = c.annotation_names()
            if anns & {"RestController", "Controller"}:
                controllers.append(c)
            elif "FeignClient" in anns:
                feigns.append(c)
            elif REPO_BASE_RE.search(c.extends_text) or "Repository" in anns:
                repos.append(c)
            elif anns & {"Service", "Component", "Transactional"} and c.kind == "class":
                services.append(c)
            if "Entity" in anns:
                entities.append(c)

        entity_to_table: dict[str, str] = {}
        entity_class: dict[str, JavaClass] = {}
        for e in entities:
            table_ann = e.annotation("Table")
            table = _first_string(table_ann[1]) if table_ann else None
            entity_to_table[e.name] = table or _snake(e.name)
            entity_class[e.name] = e

        nodes: dict[str, dict] = {}
        edges = _EdgeSet()

        def add_node(kind: str, name: str, qualified: str, file: str | None,
                     line_start: int | None, line_end: int | None,
                     metadata: dict, confidence: float = 1.0) -> str:
            node_id = f"{project_id}:{kind}:{qualified}"
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id, "kind": kind, "name": name, "qualified_name": qualified,
                    "file": file, "line_start": line_start, "line_end": line_end,
                    "metadata": metadata, "confidence": confidence,
                }
            return node_id

        def class_node(c: JavaClass, layer: str) -> str:
            return add_node("logic", c.name, c.qualified, c.file, c.line_start, c.line_end,
                            {"layer": layer, "language": "java"})

        logic_ids: dict[str, str] = {}
        for c in controllers:
            logic_ids[c.qualified] = class_node(c, "controller")
        for c in services:
            layer = "service" if "Service" in c.annotation_names() else "component"
            logic_ids[c.qualified] = class_node(c, layer)

        repo_ids: dict[str, str] = {}
        table_ids: dict[str, str] = {}

        def table_node(table: str, entity: str | None) -> str:
            if table not in table_ids:
                ec = entity_class.get(entity or "")
                table_ids[table] = add_node(
                    "table", table, table,
                    ec.file if ec else None, ec.line_start if ec else None, ec.line_end if ec else None,
                    {"entity": entity, "source": "jpa",
                     "columns": _entity_columns(ec) if ec else []},
                )
            return table_ids[table]

        for r in repos:
            m = REPO_BASE_RE.search(r.extends_text)
            entity = m.group(1) if m else None
            table = entity_to_table.get(entity or "") or (_snake(entity) if entity else None)
            repo_ids[r.qualified] = add_node(
                "data_access", r.name, r.qualified, r.file, r.line_start, r.line_end,
                {"layer": "repository", "entity": entity, "table": table, "language": "java"},
            )
            if not table:
                continue
            t_id = table_node(table, entity)
            for method in r.methods:
                query_ann = next((a for a in method.annotations if a[0] == "Query"), None)
                modifying = any(a[0] == "Modifying" for a in method.annotations)
                if query_ann:
                    from ..sql_analysis import tables_in_jpql, tables_in_sql
                    query = _first_string(query_ann[1]) or ""
                    native = "nativeQuery" in (query_ann[1] or "") and "true" in (query_ann[1] or "")
                    pairs = tables_in_sql(query) if native else tables_in_jpql(query, entity_to_table)
                    if not pairs and table:
                        pairs = [(table, "WRITE" if modifying else "READ")]
                    for tname, op in pairs:
                        op = "WRITE" if modifying else op
                        edges.add(repo_ids[r.qualified], table_node(tname, entity_to_table.get(tname)),
                                  op + "S" if op in ("READ", "WRITE") else op,
                                  0.9, evidence(r.file, method.line_start))
                else:
                    op = _classify_repo_method(method.name)
                    if op:
                        edges.add(repo_ids[r.qualified], t_id, op + "S", 0.95,
                                  evidence(r.file, method.line_start))

        endpoint_count = 0
        for c in controllers:
            base_ann = c.annotation("RequestMapping")
            base_path = _first_string(base_ann[1]) if base_ann else ""
            for method in c.methods:
                for ann_name, ann_args, ann_line in method.annotations:
                    http = MAPPING_ANNOTATIONS.get(ann_name, "skip")
                    if http == "skip":
                        continue
                    if http is None:
                        m = RM_METHOD_RE.search(ann_args or "")
                        http = m.group(1).upper() if m else "ANY"
                    path = _join_path(base_path or "", _first_string(ann_args) or "")
                    ep_name = f"{http} {path}"
                    ep_id = add_node("entry_point", ep_name, ep_name, c.file,
                                     method.line_start, method.line_end,
                                     {"http_method": http, "path": path,
                                      "handler": f"{c.name}.{method.name}", "controller": c.qualified})
                    edges.add(ep_id, logic_ids[c.qualified], "HANDLES", 1.0,
                              evidence(c.file, method.line_start))
                    endpoint_count += 1

        # Message consumers: @KafkaListener / @RabbitListener / @JmsListener / @SqsListener /
        # @StreamListener / @EventListener. Each becomes an entry_point fed by a topic/queue,
        # so the messaging flow (topic → listener → service → repo → table) shows on the map.
        service_quals = {c.qualified for c in controllers + services}
        listener_classes: list[JavaClass] = []
        seen_listener_q: set[str] = set()
        for c in classes:
            class_has_listener = False
            for method in c.methods:
                for ann_name, ann_args, ann_line in method.annotations:
                    spec = LISTENER_ANNOTATIONS.get(ann_name)
                    if spec is None:
                        continue
                    trigger, dest_kind = spec
                    m = LISTENER_DEST_RE.search(ann_args or "")
                    raw = m.group(1) if m else _first_string(ann_args or "")
                    dest = resolve_placeholder(raw)
                    label = trigger.upper()
                    ep_name = f"{label} {dest}" if dest else f"{label} {c.name}.{method.name}"
                    ep_meta = {"http_method": label, "path": dest or "",
                               "handler": f"{c.name}.{method.name}", "controller": c.qualified,
                               "trigger": trigger, "destination": dest}
                    if raw and raw != dest:
                        ep_meta["destination_property"] = raw
                    ep_id = add_node("entry_point", ep_name, ep_name, c.file,
                                     method.line_start, method.line_end, ep_meta)
                    endpoint_count += 1
                    class_has_listener = True
                    cls_id = logic_ids.get(c.qualified)
                    if cls_id is None:
                        cls_id = class_node(c, "listener")
                        logic_ids[c.qualified] = cls_id
                    edges.add(ep_id, cls_id, "HANDLES", 1.0, evidence(c.file, method.line_start))
                    if dest and dest_kind:
                        d_meta = {"messaging": trigger, "source": "code"}
                        if raw and raw != dest:
                            d_meta["property"] = raw
                        d_id = add_node(dest_kind, dest, dest, None, None, None, d_meta)
                        edges.add(d_id, ep_id, "DELIVERS_TO", 0.9, evidence(c.file, ann_line))
            if class_has_listener and c.qualified not in service_quals and c.qualified not in seen_listener_q:
                listener_classes.append(c)
                seen_listener_q.add(c.qualified)

        feign_method_ids: dict[tuple[str, str], str] = {}
        feign_names = {f.name for f in feigns}
        for f in feigns:
            ann = f.annotation("FeignClient")
            args = ann[1] if ann else ""
            service = None
            m = re.search(r'(?:name|value)\s*=\s*"([^"]+)"', args or "")
            if m:
                service = m.group(1)
            else:
                service = _first_string(args) or f.name
            for method in f.methods:
                for ann_name, ann_args, _ in method.annotations:
                    http = MAPPING_ANNOTATIONS.get(ann_name, "skip")
                    if http == "skip":
                        continue
                    if http is None:
                        mm = RM_METHOD_RE.search(ann_args or "")
                        http = mm.group(1).upper() if mm else "ANY"
                    path = _first_string(ann_args) or "/"
                    out_name = f"{service}: {http} {path}"
                    out_id = add_node("outbound_call", out_name, out_name, f.file,
                                      method.line_start, method.line_end,
                                      {"client": "feign", "service": service,
                                       "http_method": http, "url_template": path}, 0.95)
                    feign_method_ids[(f.name, method.name)] = out_id

        callable_layers = {**logic_ids}
        for c in controllers + services + listener_classes:
            for method in c.methods:
                src_id = callable_layers.get(c.qualified)
                if src_id is None:
                    continue
                for inv in method.invocations:
                    receiver = inv["receiver"]
                    if not receiver:
                        continue
                    rtype = c.fields.get(receiver)
                    if not rtype:
                        continue
                    ev = evidence(c.file, inv["line"])
                    if rtype in HTTP_CLIENT_TYPES:
                        call_name = REST_CALL_METHODS.get(inv["name"])
                        url = next((s for s in inv["str_args"]
                                    if s.startswith(("http://", "https://", "/"))), None)
                        if call_name and url:
                            out_name = f"{call_name} {url}"
                            out_id = add_node("outbound_call", out_name, out_name, c.file,
                                              inv["line"], inv["line"],
                                              {"client": rtype.lower(), "http_method": call_name,
                                               "url_template": url}, 0.7)
                            edges.add(src_id, out_id, "MAKES_CALL", 0.7, ev)
                        continue
                    if rtype in feign_names:
                        out_id = feign_method_ids.get((rtype, inv["name"]))
                        if out_id:
                            edges.add(src_id, out_id, "MAKES_CALL", 0.95, ev)
                        continue
                    msg = MESSAGING_TEMPLATE_TYPES.get(rtype.split("<", 1)[0].strip())
                    if msg and inv["name"] in SEND_METHODS:
                        trigger, dest_kind = msg
                        raw = next((s for s in inv["str_args"]
                                    if s and not s.startswith(("http://", "https://", "/"))), None)
                        dest = resolve_placeholder(raw)
                        if dest:
                            d_meta = {"messaging": trigger, "source": "code"}
                            if raw and raw != dest:
                                d_meta["property"] = raw
                            d_id = add_node(dest_kind, dest, dest, None, None, None, d_meta)
                            edges.add(src_id, d_id, "PRODUCES", 0.8, ev)
                        continue
                    targets: list[tuple[JavaClass, float]] = []
                    for target in by_name.get(rtype, []):
                        if target.qualified in repo_ids:
                            edges.add(src_id, repo_ids[target.qualified], "USES", 0.95, ev)
                            op = _classify_repo_method(inv["name"])
                            table = target and nodes[repo_ids[target.qualified]]["metadata"].get("table")
                            if op and table:
                                edges.add(repo_ids[target.qualified], table_node(table, None),
                                          op + "S", 0.9, ev)
                        elif target.kind == "interface":
                            candidates = impls.get(rtype, [])
                            conf = 0.9 if len(candidates) == 1 else 0.5
                            targets.extend((impl, conf) for impl in candidates)
                        else:
                            targets.append((target, 0.95))
                    for target, conf in targets:
                        dst_id = logic_ids.get(target.qualified)
                        if dst_id and dst_id != src_id:
                            edges.add(src_id, dst_id, "CALLS", conf, ev)

        stats = {
            "classes": len(classes), "controllers": len(controllers), "services": len(services),
            "repositories": len(repos), "entities": len(entities), "endpoints": endpoint_count,
        }
        node_list = list(nodes.values())
        for n in node_list:
            n["metadata"]["extractor"] = "spring"
        return node_list, edges.all(), stats
