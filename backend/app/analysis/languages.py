from functools import lru_cache
from pathlib import Path

import tree_sitter
from tree_sitter_language_pack import get_language

EXT_LANG = {
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".dart": "dart",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".php": "php",
    ".rb": "ruby",
    ".cs": "csharp",
}

SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "target", "build", "dist", "out",
    ".gradle", "vendor", "__pycache__", ".venv", "venv", ".idea", ".vscode",
    "Pods", ".next", ".nuxt", "coverage", ".mvn", "bin", "obj", ".dart_tool",
}


def language_for(path: str) -> str | None:
    return EXT_LANG.get(Path(path).suffix.lower())


@lru_cache(maxsize=32)
def parser_for(lang: str) -> tree_sitter.Parser | None:
    try:
        return tree_sitter.Parser(get_language(lang))
    except Exception:
        return None


def parse_source(lang: str, source: bytes) -> tree_sitter.Tree | None:
    parser = parser_for(lang)
    if parser is None:
        return None
    try:
        return parser.parse(source)
    except Exception:
        return None


def node_text(node: tree_sitter.Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def iter_source_files(root: Path):
    """Yield (absolute_path, relative_path, language) for parseable files under root."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        lang = language_for(path.name)
        if lang is not None:
            yield path, str(rel), lang
