"""Model / DTO extractor: the data contracts apps exchange.

Detects data classes, records, JPA entities, and DTO/Request/Response types across
Java / Kotlin / TypeScript -> `model` nodes. The linker then connects a model declared
in two projects (e.g. an `OrderDto` the mobile app sends and the backend receives) as a
SHARED_MODEL link, so you can see which contracts flow between apps.
"""
import re

from ..languages import walk_files

MAX_BYTES = 600 * 1024
_DTO_SUFFIX = r"(?:Dto|DTO|Request|Response|Payload|Vo|VO|Model|Resource|Record|Schema|Entity)"

# Kotlin: data class X ; Java: record X( ; annotated Java class ; DTO-suffixed class
_KT_DATA_RE = re.compile(r"\bdata\s+class\s+([A-Z]\w*)")
_JAVA_RECORD_RE = re.compile(r"\brecord\s+([A-Z]\w*)\s*\(")
_JAVA_ANNOT_RE = re.compile(
    r"@(?:Data|Value|Entity|Embeddable|Builder|Document|Table)\b[\s\S]{0,400}?\bclass\s+([A-Z]\w*)")
_SUFFIX_CLASS_RE = re.compile(rf"\b(?:class|interface)\s+([A-Z]\w*{_DTO_SUFFIX})\b")
# TypeScript: interface/type X, and DTO-suffixed class
_TS_IFACE_RE = re.compile(r"\b(?:export\s+)?interface\s+([A-Z]\w*)")
_TS_TYPE_RE = re.compile(r"\b(?:export\s+)?type\s+([A-Z]\w*)\s*=\s*[\{\w]")
_TS_SUFFIX_RE = re.compile(rf"\b(?:export\s+)?class\s+([A-Z]\w*{_DTO_SUFFIX})\b")

# names that are almost never a real cross-app contract — avoid noise
_SKIP = {"Builder", "Companion", "Test", "Tests", "Impl", "Base", "Abstract", "Config",
         "Application", "Exception", "Error", "Utils", "Util", "Constants", "Mapper"}


class ModelExtractor:
    name = "models"

    def extract(self, project_id: str, src_root):
        nodes: dict[str, dict] = {}
        stats = {"models": 0}

        def add(name: str, kind_label: str, rel: str, line: int):
            if name in _SKIP or len(name) < 3 or stats["models"] >= 2000:
                return
            nid = f"{project_id}:model:{name}"
            if nid not in nodes:
                nodes[nid] = {
                    "id": nid, "kind": "model", "name": name, "qualified_name": name,
                    "file": rel, "line_start": line, "line_end": line,
                    "metadata": {"model_type": kind_label, "extractor": self.name}, "confidence": 0.7}
                stats["models"] += 1

        seen = 0
        for p in walk_files(src_root):
            ext = p.suffix.lower()
            if ext not in {".java", ".kt", ".ts", ".tsx"}:
                continue
            seen += 1
            if seen > 40000:
                break
            rel = str(p.relative_to(src_root))
            try:
                text = p.read_text("utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > MAX_BYTES:
                continue
            line_at = lambda m: text.count("\n", 0, m.start()) + 1  # noqa: E731
            if ext in {".java", ".kt"}:
                for m in _KT_DATA_RE.finditer(text):
                    add(m.group(1), "data", rel, line_at(m))
                for m in _JAVA_RECORD_RE.finditer(text):
                    add(m.group(1), "record", rel, line_at(m))
                for m in _JAVA_ANNOT_RE.finditer(text):
                    add(m.group(1), "entity", rel, line_at(m))
                for m in _SUFFIX_CLASS_RE.finditer(text):
                    add(m.group(1), "dto", rel, line_at(m))
            else:  # ts/tsx
                for m in _TS_IFACE_RE.finditer(text):
                    add(m.group(1), "interface", rel, line_at(m))
                for m in _TS_TYPE_RE.finditer(text):
                    add(m.group(1), "type", rel, line_at(m))
                for m in _TS_SUFFIX_RE.finditer(text):
                    add(m.group(1), "dto", rel, line_at(m))

        return list(nodes.values()), [], stats
