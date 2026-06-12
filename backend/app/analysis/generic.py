import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .languages import iter_source_files, node_text, parse_source

CLASS_NODE_TYPES = {
    "class_declaration", "class_definition", "interface_declaration",
    "object_declaration", "enum_declaration", "trait_declaration",
    "class_specifier", "protocol_declaration", "struct_declaration",
    "annotation_type_declaration", "record_declaration",
}
FUNC_NODE_TYPES = {
    "method_declaration", "function_definition", "function_declaration",
    "method_definition", "constructor_declaration", "function_item",
    "fun_declaration", "function_signature",
}

ROUTE_RE = re.compile(r"^/[A-Za-z0-9_\-./:{}$]*$")
SQL_RE = re.compile(r"^\s*(select|insert|update|delete|merge|with|create\s+table)\b", re.I)
URL_RE = re.compile(r"^(https?://|\$\{[^}]+\}/)")
MAX_PARSE_BYTES = 2 * 1024 * 1024


@dataclass
class ParsedFile:
    path: str
    language: str
    source: bytes
    tree: object
    loc: int
    sha: str


@dataclass
class GenericResult:
    files: list[ParsedFile] = field(default_factory=list)
    symbols: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


def _symbol_name(node, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return node_text(name_node, source)
    for child in node.children:
        if child.type == "identifier":
            return node_text(child, source)
    return None


def _classify_string(value: str) -> str | None:
    v = value.strip()
    if len(v) < 2 or len(v) > 500 or "\n" in v:
        return None
    if SQL_RE.match(v) and len(v) > 12:
        return "sql"
    if URL_RE.match(v):
        return "url"
    if ROUTE_RE.match(v) and len(v) >= 2:
        return "route"
    return None


def scan_file(rel_path: str, language: str, source: bytes) -> tuple[ParsedFile | None, list[dict], list[dict]]:
    tree = parse_source(language, source)
    if tree is None:
        return None, [], []
    sha = hashlib.sha1(source).hexdigest()
    pf = ParsedFile(rel_path, language, source, tree, source.count(b"\n") + 1, sha)
    symbols: list[dict] = []
    candidates: list[dict] = []
    seen_candidates: set[tuple] = set()

    stack = [(tree.root_node, None)]
    while stack:
        node, parent_name = stack.pop()
        ntype = node.type
        next_parent = parent_name
        if ntype in CLASS_NODE_TYPES or ntype in FUNC_NODE_TYPES:
            name = _symbol_name(node, source)
            if name:
                symbols.append({
                    "file": rel_path,
                    "kind": "class" if ntype in CLASS_NODE_TYPES else "function",
                    "name": name,
                    "parent": parent_name,
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                })
                if ntype in CLASS_NODE_TYPES:
                    next_parent = name
        elif "string" in ntype and node.child_count <= 3:
            raw = node_text(node, source).strip("\"'`")
            kind = _classify_string(raw)
            key = (node.start_point[0] + 1, kind, raw)
            if kind and key not in seen_candidates:
                seen_candidates.add(key)
                candidates.append({
                    "file": rel_path,
                    "line": node.start_point[0] + 1,
                    "kind": kind,
                    "value": raw,
                })
        for child in node.children:
            stack.append((child, next_parent))
    return pf, symbols, candidates


def run_generic_pass(src_root: Path, on_progress=None) -> GenericResult:
    """Tier B: parse every supported file; collect the file/symbol index and
    candidate sites (route-like strings, SQL, URLs) for Tier C and the linker."""
    result = GenericResult()
    scanned = 0
    for abs_path, rel_path, lang in iter_source_files(src_root):
        try:
            source = abs_path.read_bytes()
        except OSError:
            continue
        if len(source) > MAX_PARSE_BYTES:
            continue
        pf, symbols, candidates = scan_file(rel_path, lang, source)
        if pf is None:
            continue
        result.files.append(pf)
        result.symbols.extend(symbols)
        result.candidates.extend(candidates)
        scanned += 1
        if on_progress and scanned % 100 == 0:
            on_progress(scanned)
    return result
