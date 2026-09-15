import hashlib
import json

from pydantic import BaseModel

from ..analysis import graph
from ..config import ENRICH_MAX_SOURCE_LINES, MODEL, resolve_root
from ..db import get_conn, now


class BusinessLogicCard(BaseModel):
    purpose: str
    business_rules: list[str]
    side_effects: list[str]
    gotchas: list[str]


PROMPT = """You are writing an onboarding card for someone new to this codebase \
(possibly non-technical). Below is one component of the system and its source code.

Component: {name} (kind: {kind})
{scope_hint}
Relationships in the code graph:
{edges}

Source ({file}, lines {start}-{end} — this excerpt is the entire scope; do not speculate beyond it):
```
{source}
```

Describe, in plain language and only from facts visible in the code:
- purpose: one sentence on what this component is for
- business_rules: the key rules/validations/policies it enforces (empty list if none)
- side_effects: things it triggers beyond returning data — writes, events, emails, external calls
- gotchas: surprising or easy-to-miss behavior a newcomer should know (empty list if none)"""

SCOPE_HINTS = {
    "entry_point": "This is a single API endpoint handler. Summarize only this endpoint's behavior.",
    "logic": "This is one class/module. Summarize only what this unit itself does.",
    "data_access": "This is a data-access layer unit. Focus on what it reads and writes.",
}


def _node_source(node: dict) -> tuple[str, int, int]:
    """Source slice scoped to the node's own span. Returns (text, start_line, end_line).

    Nodes whose span is a single registration line (generic-web endpoints) are
    expanded to cover the inline handler; everything else stays within the
    node's declared lines so the model never sees more than the clicked unit.
    """
    md = node.get("metadata") or {}
    # Infra compute nodes (Lambda/ECS) are *declared* in a .tf/template, but their
    # business logic lives in the handler — summarize that instead of the IaC block.
    src_file = md.get("handler_file") or node.get("file")
    src_start = md.get("handler_line") if md.get("handler_file") else node.get("line_start")
    src_end = node.get("line_end") if not md.get("handler_file") else None
    if not src_file:
        return "", 0, 0
    conn = get_conn()
    try:
        row = conn.execute("SELECT root_path FROM projects WHERE id = ?",
                           (node["project_id"],)).fetchone()
    finally:
        conn.close()
    if row is None:
        return "", 0, 0
    path = resolve_root(row["root_path"]) / src_file
    if not path.is_file():
        return "", 0, 0
    lines = path.read_text("utf-8", errors="replace").splitlines()
    start_line = max(1, src_start or 1)
    end_line = src_end or start_line
    if end_line <= start_line:
        end_line = start_line + 60
    end_line = min(len(lines), end_line, start_line + ENRICH_MAX_SOURCE_LINES - 1)
    text = "\n".join(lines[start_line - 1:end_line])
    return text, start_line, end_line


def _edges_summary(node: dict) -> str:
    parts = []
    for e in node.get("out_edges", [])[:15]:
        parts.append(f"- {e['kind']} -> {e['dst_name']} ({e['dst_kind']})")
    for e in node.get("in_edges", [])[:15]:
        parts.append(f"- {e['src_name']} ({e['src_kind']}) {e['kind']} -> this")
    return "\n".join(parts) or "- (no edges recorded)"


def enrich_node(workspace_id: str, node_id: str) -> dict:
    node = graph.node_detail(workspace_id, node_id)
    if node is None:
        raise ValueError("node not found")
    source, src_start, src_end = _node_source(node)
    if not source:
        raise ValueError("node has no readable source to summarize")
    md = node.get("metadata") or {}
    display_file = md.get("handler_file") or node.get("file") or "unknown"
    content_hash = hashlib.sha1(f"{MODEL}\n{node_id}\n{source}".encode()).hexdigest()

    conn = get_conn()
    try:
        cached = conn.execute("SELECT card FROM summaries WHERE content_hash = ?",
                              (content_hash,)).fetchone()
        if cached:
            return json.loads(cached["card"])
    finally:
        conn.close()

    from . import provider

    prompt = PROMPT.format(
        name=node.get("qualified_name") or node["name"],
        kind=node["kind"],
        scope_hint=SCOPE_HINTS.get(node["kind"], ""),
        edges=_edges_summary(node),
        file=display_file,
        start=src_start,
        end=src_end,
        source=source,
    )
    card = provider.structured(prompt, BusinessLogicCard).model_dump()
    card["generated_from"] = {
        "file": display_file,
        "start": src_start,
        "end": src_end,
        "lines": src_end - src_start + 1,
    }

    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO summaries(content_hash, node_id, card, model, created_at)"
            " VALUES(?,?,?,?,?)",
            (content_hash, node_id, json.dumps(card), MODEL, now()),
        )
        conn.commit()
    finally:
        conn.close()
    return card
