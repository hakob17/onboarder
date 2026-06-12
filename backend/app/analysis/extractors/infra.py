"""IaC extractor (Phase 8 v1): Terraform + SAM/CloudFormation.

Turns infrastructure declarations into graph nodes — lambdas/ECS as
`infra_compute`, SQS/SNS as `queue`/`topic`, RDS/Dynamo/S3 as `datastore`,
API gateways as `gateway` — wires them (subscriptions, event source mappings,
API events) and binds compute to the code module that implements its handler.
Every node and edge carries `.tf` / template `file:line` evidence.
"""

import json
import re
from pathlib import Path

from ..languages import SKIP_DIRS

TF_COMPUTE = {"aws_lambda_function": "lambda", "aws_ecs_service": "ecs service",
              "aws_ecs_task_definition": "ecs task"}
TF_QUEUE = {"aws_sqs_queue": "sqs"}
TF_TOPIC = {"aws_sns_topic": "sns"}
TF_DATASTORE = {"aws_dynamodb_table": "dynamodb", "aws_db_instance": "rds",
                "aws_rds_cluster": "rds", "aws_elasticache_cluster": "elasticache",
                "aws_s3_bucket": "s3"}
TF_GATEWAY = {"aws_apigatewayv2_api": "api gateway", "aws_api_gateway_rest_api": "api gateway",
              "aws_lb": "load balancer"}

CF_KIND = {
    "AWS::Serverless::Function": ("infra_compute", "lambda"),
    "AWS::Lambda::Function": ("infra_compute", "lambda"),
    "AWS::SQS::Queue": ("queue", "sqs"),
    "AWS::SNS::Topic": ("topic", "sns"),
    "AWS::DynamoDB::Table": ("datastore", "dynamodb"),
    "AWS::S3::Bucket": ("datastore", "s3"),
    "AWS::Serverless::Api": ("gateway", "api gateway"),
    "AWS::ApiGateway::RestApi": ("gateway", "api gateway"),
}

TEMPLATE_NAMES = ("template.yaml", "template.yml", "serverless.template")
REF_RE = re.compile(r"\$\{(aws_\w+)\.(\w+)[.\}]")
HANDLER_EXTS = (".ts", ".js", ".mjs", ".cjs", ".py")
MAX_FILES = 100


def _clean(value):
    """python-hcl2 8.x keeps quotes on keys/strings and adds __is_block__ markers."""
    if isinstance(value, dict):
        return {
            (k.strip('"') if isinstance(k, str) else k): _clean(v)
            for k, v in value.items() if k != "__is_block__"
        }
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str) and len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _cf_loader():
    import yaml

    class CFLoader(yaml.SafeLoader):
        pass

    def unknown(loader, suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    CFLoader.add_multi_constructor("!", unknown)
    return CFLoader


def _iter_files(src_root: Path, pattern: str):
    count = 0
    for path in sorted(src_root.rglob(pattern)):
        rel = path.relative_to(src_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        count += 1
        if count > MAX_FILES:
            return
        yield path, str(rel)


def _line_of(text: str, pattern: str) -> int:
    m = re.search(pattern, text, re.M)
    return text[:m.start()].count("\n") + 1 if m else 1


def _resolve_vars(value: str, tf_vars: dict) -> str:
    if not isinstance(value, str):
        return value
    return re.sub(r"\$\{var\.(\w+)\}", lambda m: str(tf_vars.get(m.group(1), m.group(0))), value)


def _find_handler_file(src_root: Path, handler: str | None, code_uri: str | None) -> str | None:
    if not handler:
        return None
    module = handler.split("/")[-1].split(".")[0]
    if not module:
        return None
    candidates: list[str] = []
    for ext in HANDLER_EXTS:
        for path, rel in _iter_files(src_root, f"{module}{ext}"):
            if any(t in rel.lower() for t in ("test", "spec", "__mocks__")):
                continue
            candidates.append(rel)
    if not candidates:
        return None
    if code_uri:
        prefix = code_uri.strip("./").split("/")[0]
        preferred = [c for c in candidates if prefix and c.startswith(prefix)]
        if preferred:
            candidates = preferred
    return min(candidates, key=len)


class InfraExtractor:
    name = "infra"

    def extract(self, project_id: str, src_root: Path):
        nodes: dict[str, dict] = {}
        edges: dict[tuple, dict] = {}
        stats = {"compute": 0, "queues": 0, "topics": 0, "datastores": 0,
                 "gateways": 0, "endpoints": 0, "bound_handlers": 0}

        def add_node(kind, name, file, line, metadata, conf=0.9):
            node_id = f"{project_id}:{kind}:{name}"
            nodes.setdefault(node_id, {
                "id": node_id, "kind": kind, "name": name, "qualified_name": name,
                "file": file, "line_start": line, "line_end": line,
                "metadata": {**metadata, "extractor": self.name}, "confidence": conf,
            })
            return node_id

        def add_edge(src, dst, kind, conf, file, line, snippet):
            key = (src, dst, kind)
            entry = edges.setdefault(key, {"src": src, "dst": dst, "kind": kind,
                                           "confidence": conf, "evidence": []})
            ev = {"file": file, "line": line, "snippet": snippet[:200]}
            if ev not in entry["evidence"] and len(entry["evidence"]) < 10:
                entry["evidence"].append(ev)

        def add_module(rel_path: str) -> str:
            stem = rel_path.split("/")[-1].rsplit(".", 1)[0]
            node_id = f"{project_id}:logic:{rel_path}"
            nodes.setdefault(node_id, {
                "id": node_id, "kind": "logic", "name": stem, "qualified_name": rel_path,
                "file": rel_path, "line_start": 1, "line_end": 1,
                "metadata": {"layer": "module", "extractor": self.name}, "confidence": 0.85,
            })
            return node_id

        def bind_handler(compute_id: str, handler: str | None, code_uri: str | None,
                         file: str, line: int):
            rel = _find_handler_file(src_root, handler, code_uri)
            if rel:
                module_id = add_module(rel)
                add_edge(compute_id, module_id, "RUNS", 0.85, file, line,
                         f"handler {handler}")
                stats["bound_handlers"] += 1

        # ---------- Terraform ----------
        tf_resources: dict[str, dict] = {}  # "aws_sqs_queue.foo" -> {node_id, kind}
        tf_vars: dict[str, str] = {}
        tf_docs: list[tuple[dict, str, str]] = []
        try:
            import hcl2
        except ImportError:
            hcl2 = None
        if hcl2 is not None:
            for path, rel in _iter_files(src_root, "*.tf"):
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        doc = _clean(hcl2.load(f))
                except Exception:
                    continue
                tf_docs.append((doc, rel, path.read_text("utf-8", errors="replace")))
                for block in doc.get("variable", []):
                    for vname, vdef in block.items():
                        if isinstance(vdef, dict) and "default" in vdef:
                            tf_vars[vname] = vdef["default"]

            def res_line(text, rtype, rname):
                return _line_of(text, rf'resource\s+"{rtype}"\s+"{rname}"')

            for doc, rel, text in tf_docs:
                for block in doc.get("resource", []):
                    for rtype, instances in block.items():
                        for rname, attrs in (instances or {}).items():
                            if not isinstance(attrs, dict):
                                continue
                            line = res_line(text, rtype, rname)
                            ref = f"{rtype}.{rname}"
                            display = _resolve_vars(
                                str(attrs.get("function_name") or attrs.get("name") or rname),
                                tf_vars)
                            if rtype in TF_COMPUTE:
                                env = (attrs.get("environment") or [{}])
                                env_vars = {}
                                if isinstance(env, list) and env and isinstance(env[0], dict):
                                    env_vars = env[0].get("variables") or {}
                                node_id = add_node("infra_compute", display, rel, line, {
                                    "infra_type": TF_COMPUTE[rtype], "source": "terraform",
                                    "handler": attrs.get("handler"),
                                    "runtime": attrs.get("runtime"),
                                    "env": env_vars,
                                })
                                tf_resources[ref] = {"id": node_id, "kind": "infra_compute"}
                                stats["compute"] += 1
                                bind_handler(node_id, attrs.get("handler"), None, rel, line)
                            elif rtype in TF_QUEUE:
                                node_id = add_node("queue", display, rel, line,
                                                   {"infra_type": "sqs", "source": "terraform"})
                                tf_resources[ref] = {"id": node_id, "kind": "queue"}
                                stats["queues"] += 1
                            elif rtype in TF_TOPIC:
                                node_id = add_node("topic", display, rel, line,
                                                   {"infra_type": "sns", "source": "terraform"})
                                tf_resources[ref] = {"id": node_id, "kind": "topic"}
                                stats["topics"] += 1
                            elif rtype in TF_DATASTORE:
                                node_id = add_node("datastore", display, rel, line, {
                                    "infra_type": TF_DATASTORE[rtype], "source": "terraform"})
                                tf_resources[ref] = {"id": node_id, "kind": "datastore"}
                                stats["datastores"] += 1
                            elif rtype in TF_GATEWAY:
                                node_id = add_node("gateway", display, rel, line, {
                                    "infra_type": TF_GATEWAY[rtype], "source": "terraform"})
                                tf_resources[ref] = {"id": node_id, "kind": "gateway"}
                                stats["gateways"] += 1

            def refs_in(value) -> list[str]:
                return [f"{t}.{n}" for t, n in REF_RE.findall(str(value))]

            for doc, rel, text in tf_docs:
                for block in doc.get("resource", []):
                    for rtype, instances in block.items():
                        for rname, attrs in (instances or {}).items():
                            if not isinstance(attrs, dict):
                                continue
                            line = res_line(text, rtype, rname)
                            if rtype == "aws_sns_topic_subscription":
                                topics = [r for r in refs_in(attrs.get("topic_arn", "")) if r in tf_resources]
                                targets = [r for r in refs_in(attrs.get("endpoint", "")) if r in tf_resources]
                                for t in topics:
                                    for tgt in targets:
                                        add_edge(tf_resources[t]["id"], tf_resources[tgt]["id"],
                                                 "DELIVERS_TO", 0.9, rel, line, f"subscription {rname}")
                            elif rtype == "aws_lambda_event_source_mapping":
                                sources = [r for r in refs_in(attrs.get("event_source_arn", "")) if r in tf_resources]
                                funcs = [r for r in refs_in(str(attrs.get("function_name", ""))) if r in tf_resources]
                                for s in sources:
                                    for fn in funcs:
                                        add_edge(tf_resources[s]["id"], tf_resources[fn]["id"],
                                                 "TRIGGERS", 0.9, rel, line, f"event source mapping {rname}")
                            elif rtype == "aws_apigatewayv2_route":
                                route_key = _resolve_vars(str(attrs.get("route_key", "")), tf_vars)
                                m = re.match(r"(GET|POST|PUT|DELETE|PATCH|ANY)\s+(/\S*)", route_key)
                                if m:
                                    ep_name = f"{m.group(1)} {m.group(2)}"
                                    ep_id = add_node("entry_point", ep_name, rel, line, {
                                        "http_method": m.group(1), "path": m.group(2),
                                        "handler": rname, "source": "terraform"})
                                    stats["endpoints"] += 1
                                    for tgt in [r for r in refs_in(str(attrs.get("target", ""))) if r in tf_resources]:
                                        add_edge(ep_id, tf_resources[tgt]["id"], "HANDLES",
                                                 0.85, rel, line, route_key)
                            elif rtype in TF_COMPUTE:
                                env = (attrs.get("environment") or [{}])
                                env_vars = env[0].get("variables") if isinstance(env, list) and env and isinstance(env[0], dict) else {}
                                for value in (env_vars or {}).values():
                                    for r in refs_in(value):
                                        if r in tf_resources and tf_resources[r]["kind"] in ("datastore", "queue", "topic"):
                                            ref_self = f"{rtype}.{rname}"
                                            if ref_self in tf_resources:
                                                add_edge(tf_resources[ref_self]["id"], tf_resources[r]["id"],
                                                         "USES_STORE", 0.75, rel, line, f"env ref {r}")

        # ---------- SAM / CloudFormation ----------
        try:
            import yaml
            loader = _cf_loader()
        except ImportError:
            yaml = None
            loader = None
        if yaml is not None:
            template_files = [(p, r) for name in TEMPLATE_NAMES for p, r in _iter_files(src_root, name)]
            cf_names: dict[str, str] = {}
            for path, rel in template_files:
                text = path.read_text("utf-8", errors="replace")
                try:
                    doc = yaml.load(text, Loader=loader)
                except Exception:
                    continue
                resources = (doc or {}).get("Resources") or {}
                if not isinstance(resources, dict):
                    continue
                for res_name, res in resources.items():
                    if not isinstance(res, dict) or res.get("Type") not in CF_KIND:
                        continue
                    kind, infra_type = CF_KIND[res["Type"]]
                    props = res.get("Properties") or {}
                    line = _line_of(text, rf"^\s{{2}}{re.escape(res_name)}:\s*$")
                    metadata = {"infra_type": infra_type, "source": "sam"}
                    if kind == "infra_compute":
                        metadata.update({
                            "handler": props.get("Handler"),
                            "runtime": props.get("Runtime"),
                            "env": (props.get("Environment") or {}).get("Variables") or {},
                        })
                    node_id = add_node(kind, res_name, rel, line, metadata)
                    cf_names[res_name] = node_id
                    key = {"infra_compute": "compute", "queue": "queues", "topic": "topics",
                           "datastore": "datastores", "gateway": "gateways"}[kind]
                    stats[key] += 1
                    if kind == "infra_compute":
                        bind_handler(node_id, props.get("Handler"), str(props.get("CodeUri") or ""),
                                     rel, line)
                        for ev_name, event in (props.get("Events") or {}).items():
                            if not isinstance(event, dict):
                                continue
                            etype = event.get("Type")
                            eprops = event.get("Properties") or {}
                            if etype in ("Api", "HttpApi") and eprops.get("Path"):
                                method = str(eprops.get("Method", "ANY")).upper()
                                ep_name = f"{method} {eprops['Path']}"
                                ep_line = _line_of(text, rf"^\s+{re.escape(ev_name)}:\s*$")
                                ep_id = add_node("entry_point", ep_name, rel, ep_line, {
                                    "http_method": method, "path": eprops["Path"],
                                    "handler": res_name, "source": "sam"})
                                stats["endpoints"] += 1
                                add_edge(ep_id, node_id, "HANDLES", 0.9, rel, ep_line,
                                         f"{etype} event {ev_name}")
                            elif etype == "SQS":
                                queue_ref = str(eprops.get("Queue", ""))
                                for ref_name, ref_id in cf_names.items():
                                    if ref_name in queue_ref:
                                        add_edge(ref_id, node_id, "TRIGGERS", 0.85, rel, line,
                                                 f"SQS event {ev_name}")

        total = sum(v for k, v in stats.items() if k != "bound_handlers")
        return list(nodes.values()), list(edges.values()), (stats if total else {})
