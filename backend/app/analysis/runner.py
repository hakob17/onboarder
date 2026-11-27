import threading
import traceback
from pathlib import Path

from ..config import llm_enabled, resolve_root
from ..db import emit_event, get_conn
from .extractors import find_extractor
from .extractors.generic_web import GenericWebExtractor
from .generic import run_generic_pass
from .graph import persist_analysis
from .linker import link_workspace


def _set_status(project_id: str, status: str, error: str | None = None) -> None:
    conn = get_conn()
    try:
        conn.execute("UPDATE projects SET status = ?, error = ? WHERE id = ?",
                     (status, error, project_id))
        conn.commit()
    finally:
        conn.close()


def build_project_graph(project: dict, src_root: Path, allow_llm: bool = True, emit=None):
    """Run the full extraction pipeline on a directory without persisting.

    Used by live analysis (which persists the result) and by snapshots
    (git-ref baselines analyze a temp checkout with the SAME project id so
    node ids stay diffable). Tier C (LLM) only runs for live analysis.
    """
    generic = run_generic_pass(
        src_root,
        on_progress=(lambda n: emit("files_scanned", {"count": n})) if emit else None,
    )
    nodes_by_id: dict = {}
    edges: list = []
    stats: dict = {}
    covered_langs: set = set()

    def _run(label: str, fn):
        """Run one extractor defensively: a failure logs + is skipped, so one bad file
        can't fail the whole project (it just produces fewer nodes)."""
        try:
            return fn()
        except Exception as e:
            import traceback
            print(f"[onboarder] extractor '{label}' failed on {project.get('id')}: {e}", flush=True)
            traceback.print_exc()
            if emit:
                emit("extractor_failed", {"extractor": label, "error": str(e)})
            return None

    extractor = find_extractor(project["stack"])
    if extractor is not None:
        lang_files = [(f.path, f.tree, f.source) for f in generic.files if f.language == "java"]
        if lang_files:
            res = _run(extractor.name, lambda: extractor.extract(project["id"], lang_files))
            if res is not None:
                t_nodes, t_edges, stats = res
                nodes_by_id = {n["id"]: n for n in t_nodes}
                edges = list(t_edges)
                stats["extractor"] = extractor.name
                covered_langs = {"java"}

    gw = _run("generic-web", lambda: GenericWebExtractor().extract(
        project["id"], generic, exclude_langs=covered_langs))
    if gw is not None:
        gw_nodes, gw_edges, gw_stats = gw
        for n in gw_nodes:
            nodes_by_id.setdefault(n["id"], n)
        edges.extend(gw_edges)
        if gw_stats.get("endpoints") or gw_stats.get("outbound") or gw_stats.get("sql_tables"):
            stats["generic_web"] = gw_stats

    from .extractors.infra import InfraExtractor
    inf = _run("infra", lambda: InfraExtractor().extract(project["id"], src_root))
    if inf is not None:
        inf_nodes, inf_edges, inf_stats = inf
        for n in inf_nodes:
            nodes_by_id.setdefault(n["id"], n)
        edges.extend(inf_edges)
        if inf_stats:
            stats["infra"] = inf_stats

    from .extractors.graphql_fed import GraphQLFederationExtractor
    gql = _run("graphql", lambda: GraphQLFederationExtractor().extract(project["id"], src_root))
    if gql is not None:
        gql_nodes, gql_edges, gql_stats = gql
        for n in gql_nodes:
            nodes_by_id.setdefault(n["id"], n)
        edges.extend(gql_edges)
        if gql_stats:
            stats["graphql"] = gql_stats

    if allow_llm and not any(n["kind"] == "entry_point" for n in nodes_by_id.values()) and llm_enabled():
        try:
            from .llm_extract import llm_extract
            l_nodes, l_edges, l_stats = llm_extract(project["id"], generic)
            for n in l_nodes:
                nodes_by_id.setdefault(n["id"], n)
            edges.extend(l_edges)
            stats.update(l_stats)
        except Exception as e:
            if emit:
                emit("llm_extract_failed", {"error": str(e)})

    nodes = list(nodes_by_id.values())

    def _migrations():
        from .migrations import apply_schemas, harvest_schemas
        return apply_schemas(project["id"], nodes, harvest_schemas(src_root))
    applied = _run("migrations", _migrations)
    if applied:
        stats["migration_tables"] = applied

    stats.update({
        "files": len(generic.files),
        "symbols": len(generic.symbols),
        "candidates": len(generic.candidates),
        "truncated": generic.truncated,
    })
    return generic, nodes, edges, stats


def analyze_project(workspace_id: str, project_id: str) -> None:
    conn = get_conn()
    try:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    finally:
        conn.close()
    if project is None:
        return
    src_root = resolve_root(project["root_path"])
    _set_status(project_id, "analyzing")
    emit_event(workspace_id, project_id, "analysis_started", {"stack": project["stack"]})
    try:
        generic, nodes, edges, stats = build_project_graph(
            dict(project), src_root, allow_llm=True,
            emit=lambda t, p: emit_event(workspace_id, project_id, t, p),
        )
        persist_analysis(workspace_id, project_id, generic, nodes, edges, stats)
        _set_status(project_id, "ready")
        emit_event(workspace_id, project_id, "analysis_completed",
                   {"nodes": len(nodes), "edges": len(edges), **stats})
        try:
            link_workspace(workspace_id)
        except Exception as e:
            emit_event(workspace_id, None, "link_failed", {"error": str(e)})
    except Exception as e:
        _set_status(project_id, "failed", f"{e}")
        emit_event(workspace_id, project_id, "analysis_failed",
                   {"error": str(e), "trace": traceback.format_exc()[-2000:]})


import os as _os

# Analyze at most a few projects at once: a folder of large repos otherwise parses all of
# them in parallel and exhausts the engine's memory. Each finished project frees its trees.
_ANALYSIS_SEM = threading.Semaphore(int(_os.environ.get("ONBOARDER_ANALYSIS_CONCURRENCY", "2")))


def _analyze_guarded(workspace_id: str, project_id: str) -> None:
    with _ANALYSIS_SEM:
        analyze_project(workspace_id, project_id)


def analyze_in_background(workspace_id: str, project_id: str) -> None:
    try:
        from .snapshots import maybe_auto_snapshot
        maybe_auto_snapshot(workspace_id)
    except Exception:
        pass
    threading.Thread(
        target=_analyze_guarded, args=(workspace_id, project_id), daemon=True
    ).start()
