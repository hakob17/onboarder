import re

import sqlglot
from sqlglot import expressions as exp

WRITE_STMTS = (exp.Insert, exp.Update, exp.Delete, exp.Merge)
_JPQL_FROM_RE = re.compile(r"\bfrom\s+([A-Za-z_]\w*)", re.I)
_JPQL_DML_RE = re.compile(r"^\s*(update|delete)\b", re.I)


def tables_in_sql(sql: str) -> list[tuple[str, str]]:
    """Parse SQL and return [(table_name, 'READ'|'WRITE'), ...]."""
    results: dict[tuple[str, str], None] = {}
    try:
        statements = sqlglot.parse(sql)
    except Exception:
        return []
    for stmt in statements:
        if stmt is None:
            continue
        write_targets: set[str] = set()
        if isinstance(stmt, WRITE_STMTS):
            target = stmt.this
            if target is not None:
                for t in [target] if isinstance(target, exp.Table) else list(target.find_all(exp.Table)):
                    write_targets.add(t.name.lower())
        for t in stmt.find_all(exp.Table):
            name = t.name.lower()
            if not name:
                continue
            op = "WRITE" if name in write_targets else "READ"
            results[(name, op)] = None
    return list(results.keys())


def tables_in_jpql(query: str, entity_to_table: dict[str, str]) -> list[tuple[str, str]]:
    """Best-effort JPQL: map `FROM EntityName` to its table; UPDATE/DELETE are writes."""
    op = "WRITE" if _JPQL_DML_RE.match(query) else "READ"
    out = []
    for entity in _JPQL_FROM_RE.findall(query):
        table = entity_to_table.get(entity)
        if table:
            out.append((table, op))
    return out
