"""Migration schema harvest: CREATE TABLE statements in .sql files become the
authoritative column lists for table nodes (overriding entity/sql-derived ones)."""

from pathlib import Path

import sqlglot
from sqlglot import expressions as exp

from .languages import SKIP_DIRS

MAX_SQL_FILES = 200
MAX_SQL_BYTES = 256 * 1024


def harvest_schemas(src_root: Path) -> dict[str, dict]:
    """→ {table_name: {columns: [{name,type,pk}], file, line}}"""
    schemas: dict[str, dict] = {}
    if not src_root.exists():
        return schemas
    count = 0
    for path in sorted(src_root.rglob("*.sql")):
        rel = path.relative_to(src_root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        count += 1
        if count > MAX_SQL_FILES:
            break
        try:
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > MAX_SQL_BYTES:
            continue
        try:
            statements = sqlglot.parse(text, read="postgres")
        except Exception:
            try:
                statements = sqlglot.parse(text)
            except Exception:
                continue
        for stmt in statements:
            if not isinstance(stmt, exp.Create) or stmt.kind != "TABLE":
                continue
            schema = stmt.this
            if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
                continue
            table = schema.this.name.lower()
            table_pks = set()
            for e in schema.expressions:
                if isinstance(e, exp.PrimaryKey):
                    table_pks = {c.name for c in e.expressions}
            columns = []
            for e in schema.expressions:
                if not isinstance(e, exp.ColumnDef):
                    continue
                pk = e.name in table_pks or any(
                    isinstance(c.kind, exp.PrimaryKeyColumnConstraint) for c in (e.constraints or []))
                columns.append({
                    "name": e.name,
                    "type": e.kind.sql(dialect="postgres").lower() if e.kind else "",
                    "pk": pk,
                })
            if columns:
                schemas[table] = {
                    "columns": columns,
                    "file": str(rel),
                    "line": (stmt.meta or {}).get("line", 1) if hasattr(stmt, "meta") else 1,
                }
    return schemas


def apply_schemas(project_id: str, nodes: list[dict], schemas: dict[str, dict]) -> int:
    """Override table-node columns with migration truth; add migration-only tables."""
    if not schemas:
        return 0
    applied = 0
    seen_tables = set()
    for node in nodes:
        if node["kind"] != "table":
            continue
        seen_tables.add(node["name"].lower())
        schema = schemas.get(node["name"].lower())
        if schema:
            node["metadata"]["columns"] = schema["columns"]
            node["metadata"]["schema_source"] = "migration"
            applied += 1
    for table, schema in schemas.items():
        if table in seen_tables:
            continue
        nodes.append({
            "id": f"{project_id}:table:{table}",
            "kind": "table", "name": table, "qualified_name": table,
            "file": schema["file"], "line_start": schema["line"], "line_end": schema["line"],
            "metadata": {"columns": schema["columns"], "schema_source": "migration",
                         "source": "migration", "extractor": "migrations"},
            "confidence": 0.9,
        })
        applied += 1
    return applied
