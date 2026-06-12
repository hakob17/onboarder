"""Tier C: LLM-assisted extraction for stacks the deterministic tiers missed.

Candidate sites from the generic pass are batched to the model with a strict
output schema; every returned fact must cite a line that actually exists in the
named file or it is dropped. Runs only when ANTHROPIC_API_KEY is configured.
"""

from pydantic import BaseModel

from ..config import MODEL, llm_enabled

MAX_CANDIDATE_FILES = 30
SNIPPET_RADIUS = 6
MAX_PROMPT_CHARS = 60_000


class XEndpoint(BaseModel):
    method: str
    path: str
    file: str
    line: int


class XOutbound(BaseModel):
    method: str
    url_template: str
    file: str
    line: int


class XQuery(BaseModel):
    tables: list[str]
    operation: str  # READ | WRITE
    file: str
    line: int


class ExtractedFacts(BaseModel):
    endpoints: list[XEndpoint]
    outbound_calls: list[XOutbound]
    queries: list[XQuery]


PROMPT = """You are a static-analysis assistant. Below are excerpts from source files of one \
project, each line prefixed with `file:line\\t`. Extract, ONLY from what is visible:

- endpoints: HTTP routes this project EXPOSES (method, path)
- outbound_calls: HTTP/gRPC calls this project MAKES to other systems (keep URL templates \
verbatim, including env-var placeholders)
- queries: SQL statements (table names, operation READ or WRITE)

Cite the exact file and line each fact comes from. Do not guess facts that are not in the excerpts.

{excerpts}"""


def _excerpts(generic) -> str:
    by_file: dict[str, list[int]] = {}
    for c in generic.candidates:
        by_file.setdefault(c["file"], []).append(c["line"])
    chunks: list[str] = []
    total = 0
    for path, lines in list(by_file.items())[:MAX_CANDIDATE_FILES]:
        pf = next((f for f in generic.files if f.path == path), None)
        if pf is None:
            continue
        text_lines = pf.source.decode("utf-8", "replace").splitlines()
        wanted: set[int] = set()
        for ln in lines:
            wanted.update(range(max(1, ln - SNIPPET_RADIUS), min(len(text_lines), ln + SNIPPET_RADIUS) + 1))
        block = "\n".join(f"{path}:{i}\t{text_lines[i - 1]}" for i in sorted(wanted))
        total += len(block)
        if total > MAX_PROMPT_CHARS:
            break
        chunks.append(block)
    return "\n\n".join(chunks)


def llm_extract(project_id: str, generic) -> tuple[list[dict], list[dict], dict]:
    if not llm_enabled() or not generic.candidates:
        return [], [], {}
    excerpts = _excerpts(generic)
    if not excerpts:
        return [], [], {}

    from ..llm import get_client

    client = get_client()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": PROMPT.format(excerpts=excerpts)}],
        output_format=ExtractedFacts,
    )
    facts = response.parsed_output

    loc = {f.path: f.loc for f in generic.files}
    sources = {f.path: f.source for f in generic.files}

    def valid(file: str, line: int) -> bool:
        return file in loc and 1 <= line <= loc[file]

    def evidence(file: str, line: int) -> dict:
        lines = sources.get(file, b"").decode("utf-8", "replace").splitlines()
        snippet = lines[line - 1].strip()[:200] if 0 < line <= len(lines) else ""
        return {"file": file, "line": line, "snippet": snippet}

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    dropped = 0

    def add_node(node_id, kind, name, file, line, metadata):
        nodes.setdefault(node_id, {
            "id": node_id, "kind": kind, "name": name, "qualified_name": name,
            "file": file, "line_start": line, "line_end": line,
            "metadata": {**metadata, "extractor": "llm"}, "confidence": 0.6,
        })
        return node_id

    def module_for(file, line):
        stem = file.split("/")[-1].rsplit(".", 1)[0]
        return add_node(f"{project_id}:logic:{file}", "logic", stem, file, 1,
                        {"layer": "module"})

    for ep in facts.endpoints:
        if not valid(ep.file, ep.line) or not ep.path.startswith("/"):
            dropped += 1
            continue
        name = f"{ep.method.upper()} {ep.path}"
        ep_id = add_node(f"{project_id}:entry_point:{name}", "entry_point", name,
                         ep.file, ep.line, {"http_method": ep.method.upper(), "path": ep.path,
                                            "handler": ep.file.split("/")[-1]})
        edges.append({"src": ep_id, "dst": module_for(ep.file, ep.line), "kind": "HANDLES",
                      "confidence": 0.6, "evidence": [evidence(ep.file, ep.line)]})
    for ob in facts.outbound_calls:
        if not valid(ob.file, ob.line):
            dropped += 1
            continue
        name = f"{ob.method.upper()} {ob.url_template}"
        out_id = add_node(f"{project_id}:outbound_call:{name}", "outbound_call", name,
                          ob.file, ob.line, {"http_method": ob.method.upper(),
                                             "url_template": ob.url_template, "client": "llm"})
        edges.append({"src": module_for(ob.file, ob.line), "dst": out_id, "kind": "MAKES_CALL",
                      "confidence": 0.6, "evidence": [evidence(ob.file, ob.line)]})
    for q in facts.queries:
        if not valid(q.file, q.line) or q.operation.upper() not in ("READ", "WRITE"):
            dropped += 1
            continue
        for table in q.tables:
            t_id = add_node(f"{project_id}:table:{table.lower()}", "table", table.lower(),
                            q.file, q.line, {"source": "llm", "columns": []})
            edges.append({"src": module_for(q.file, q.line), "dst": t_id,
                          "kind": q.operation.upper() + "S",
                          "confidence": 0.6, "evidence": [evidence(q.file, q.line)]})

    stats = {"llm_facts": len(facts.endpoints) + len(facts.outbound_calls) + len(facts.queries),
             "llm_dropped": dropped}
    return list(nodes.values()), edges, stats
