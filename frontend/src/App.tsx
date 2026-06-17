import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, eventsUrl,
  type DiffResult, type Graph, type GraphEdge, type GraphNode, type NodeDetail,
  type Project, type SnapshotMeta, type Tour, type Workspace,
} from "./api";
import { ChatPanel } from "./components/Chat";
import { DiffPanel } from "./components/DiffPanel";
import { InfraView } from "./components/InfraView";
import { Icon } from "./icons";
import { MapGraph, type Highlight } from "./components/MapGraph";
import { NodePanel, TablePanel } from "./components/panels";
import { SettingsModal } from "./components/SettingsModal";
import { Rail, TopBar, type Persona, type RailKey } from "./components/shell";
import { exportJson, exportSvg } from "./export";
import { StarGraph } from "./components/StarGraph";
import { TourCard } from "./components/TourCard";
import { AnalysisState, UploadChrome, UploadEmpty } from "./components/Upload";
import { adaptGraph, neighborhood, pathsHighlight, type DNode } from "./model";

type Phase = "home" | "analyzing" | "workspace";
type View = "map" | "tables" | "infra" | "chat";

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("ob_theme") ?? "light");
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [phase, setPhase] = useState<Phase>("home");
  const [recents, setRecents] = useState<Workspace[]>([]);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [graphRaw, setGraphRaw] = useState<Graph | null>(null);
  const [view, setView] = useState<View>("map");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [highlight, setHighlight] = useState<Highlight | null>(null);
  const [search, setSearch] = useState("");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tour, setTour] = useState<Tour | null>(null);
  const [tourIdx, setTourIdx] = useState(0);
  const [tourBusy, setTourBusy] = useState(false);
  const [tourError, setTourError] = useState<string | null>(null);
  const [chatAsk, setChatAsk] = useState<string | null>(null);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diff, setDiff] = useState<DiffResult | null>(null);
  const [diffBase, setDiffBase] = useState("latest");
  const [diffBusy, setDiffBusy] = useState(false);
  const [snapshots, setSnapshots] = useState<SnapshotMeta[]>([]);
  const [persona, setPersona] = useState<Persona>(() => (localStorage.getItem("ob_persona") as Persona) || "dev");
  useEffect(() => { localStorage.setItem("ob_persona", persona); }, [persona]);

  // in compare mode, render the union of current graph + ghosts of removed things
  const renderRaw = useMemo<Graph | null>(() => {
    if (!graphRaw) return null;
    if (!diffOpen || !diff) return graphRaw;
    const added = new Set(diff.added_nodes.map((n) => n.id));
    const changed = new Set(diff.changed_nodes.map((c) => c.node.id));
    const tagNode = (n: GraphNode): GraphNode =>
      added.has(n.id) ? { ...n, metadata: { ...n.metadata, __diff: "added" } }
        : changed.has(n.id) ? { ...n, metadata: { ...n.metadata, __diff: "changed" } } : n;
    const addedEdges = new Set(diff.added_edges.map((e) => `${e.src}|${e.dst}|${e.kind}`));
    const tagEdge = (e: GraphEdge): GraphEdge =>
      addedEdges.has(`${e.src}|${e.dst}|${e.kind}`) ? { ...e, __diff: "added" } : e;
    return {
      nodes: [
        ...graphRaw.nodes.map(tagNode),
        ...diff.removed_nodes.map((n) => ({ ...n, metadata: { ...n.metadata, __diff: "removed" } })),
      ],
      edges: [
        ...graphRaw.edges.map(tagEdge),
        ...diff.removed_edges.map((e) => ({ ...e, __diff: "removed" as const })),
      ],
      cross_edges: graphRaw.cross_edges.map(tagEdge),
    };
  }, [graphRaw, diff, diffOpen]);

  // Manager persona shows a high-confidence "business" view: drop LLM-guessed /
  // low-confidence nodes & edges. Power keeps everything (and shows confidence).
  const personaRaw = useMemo<Graph | null>(() => {
    if (!renderRaw) return null;
    if (persona !== "pm") return renderRaw;
    const core = new Set(["entry_point", "logic", "table"]);
    const keep = (c: number, kind: string) => c >= 0.7 || core.has(kind);
    const nodes = renderRaw.nodes.filter((n) => keep(n.confidence ?? 1, n.kind));
    const ids = new Set(nodes.map((n) => n.id));
    const okEdge = (e: GraphEdge) => ids.has(e.src) && ids.has(e.dst) && (e.confidence ?? 1) >= 0.7;
    return {
      nodes,
      edges: renderRaw.edges.filter(okEdge),
      cross_edges: renderRaw.cross_edges.filter(okEdge),
    };
  }, [renderRaw, persona]);

  const g = useMemo(
    () => (personaRaw ? adaptGraph(personaRaw, projects) : null),
    [personaRaw, projects],
  );
  const projName = useMemo(
    () => new Map(projects.map((p) => [p.id, p.name.split("/").pop() ?? p.name])),
    [projects],
  );

  useEffect(() => { localStorage.setItem("ob_theme", theme); }, [theme]);
  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  useEffect(() => {
    api.health().then((h) => setLlmEnabled(h.llm_enabled)).catch(() => undefined);
    refreshRecents();
    const last = window.__ONBOARDER__?.workspaceId ?? localStorage.getItem("ob_ws");
    if (last) openWorkspace(last).catch(() => localStorage.removeItem("ob_ws"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshRecents() {
    try {
      const list = await api.listWorkspaces();
      const withProjects = await Promise.all(
        list.slice(0, 6).map(async (w) => ({ ...w, projects: await api.listProjects(w.id) })),
      );
      setRecents(withProjects.filter((w) => (w.projects?.length ?? 0) > 0 || true));
    } catch { /* backend down — upload screen still renders */ }
  }

  async function openWorkspace(id: string) {
    const w = await api.getWorkspace(id);
    setWs(w);
    setProjects(w.projects ?? []);
    localStorage.setItem("ob_ws", id);
    const busy = (w.projects ?? []).some((p) => p.status === "pending" || p.status === "analyzing");
    if (busy || (w.projects ?? []).length === 0) {
      setPhase("analyzing");
    } else {
      await loadGraph(id);
      setPhase("workspace");
      setView("map");
    }
  }

  async function loadGraph(wsId: string) {
    const [graph, ps] = await Promise.all([api.getGraph(wsId), api.listProjects(wsId)]);
    setGraphRaw(graph);
    setProjects(ps);
    setSelectedId(null);
    setDetail(null);
    setHighlight(null);
  }

  async function refreshGraph() {
    if (!ws) return;
    const [graph, ps] = await Promise.all([api.getGraph(ws.id), api.listProjects(ws.id)]);
    setGraphRaw(graph);
    setProjects(ps);
  }

  // live updates: re-analysis (save watcher, re-analyze button elsewhere) and
  // linker runs refresh the open graph without losing the current selection
  useEffect(() => {
    if (phase !== "workspace" || !ws) return;
    const es = new EventSource(eventsUrl(ws.id));
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refresh = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => void refreshGraph(), 600);
    };
    es.addEventListener("analysis_completed", refresh);
    es.addEventListener("link_completed", refresh);
    return () => {
      if (timer) clearTimeout(timer);
      es.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, ws?.id]);

  // vscode webview bridge: extension can select a node or force a refresh
  const selectByIdRef = useRef<((id: string, opts?: { toTables?: boolean }) => Promise<void>) | null>(null);
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const msg = e.data as { command?: string; nodeId?: string; question?: string };
      if (msg?.command === "select" && msg.nodeId) {
        setView("map");
        void selectByIdRef.current?.(msg.nodeId);
      } else if (msg?.command === "chat") {
        setView("chat");
        if (msg.question) setChatAsk(msg.question);
      } else if (msg?.command === "diff") {
        void openDiff();
      } else if (msg?.command === "refresh") {
        void refreshGraph();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws?.id]);

  async function handleFiles(files: File[]) {
    setUploadError(null);
    try {
      const name = files[0].name.replace(/\.zip$/i, "");
      const w = await api.createWorkspace(name);
      for (const f of files) await api.uploadZip(w.id, f);
      await openWorkspace(w.id);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    }
  }

  async function reanalyze() {
    if (!ws) return;
    await Promise.all(projects.map((p) => api.reanalyze(ws.id, p.id)));
    setPhase("analyzing");
  }

  const selectById = useCallback(async (id: string, opts?: { toTables?: boolean }) => {
    if (!ws || !g) return;
    const dn = g.byId.get(id);
    if (!dn) return;
    if (dn.type === "table" || opts?.toTables) {
      setView("tables");
    } else if (view === "tables") {
      setView("map");
    }
    setSelectedId(id);
    if (dn.type === "endpoint") {
      try {
        const { paths } = await api.trace(ws.id, id);
        const hl = pathsHighlight(paths);
        hl.nodes.add(id);
        setHighlight({ ...hl, flow: true });
      } catch { /* keep selection without highlight */ }
      try {
        setDetail(await api.getNode(ws.id, id));
      } catch {
        setDetail(null);
      }
      return;
    }
    const nb = neighborhood(g, id);
    setHighlight({ nodes: nb.nodes, edges: nb.edges });
    try {
      setDetail(await api.getNode(ws.id, id));
    } catch {
      setDetail(null);
    }
  }, [ws, g, view]);

  useEffect(() => {
    selectByIdRef.current = selectById;
  }, [selectById]);

  const onSelect = useCallback((n: DNode | null) => {
    if (!n) {
      setSelectedId(null);
      setDetail(null);
      setHighlight(null);
      return;
    }
    void selectById(n.id);
  }, [selectById]);

  // tables view with nothing selected → auto-select the busiest table
  useEffect(() => {
    if (view !== "tables" || !g || (detail?.kind === "table")) return;
    const counts = new Map<string, number>();
    for (const e of g.edges) {
      const dst = g.byId.get(e.to);
      if (dst?.type === "table") counts.set(dst.id, (counts.get(dst.id) ?? 0) + 1);
    }
    const best = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
      ?? g.nodes.find((n) => n.type === "table")?.id;
    if (best) void selectById(best, { toTables: true });
  }, [view, g]);

  // search → highlight matches
  useEffect(() => {
    if (!g) return;
    const q = search.trim().toLowerCase();
    if (!q) {
      if (!selectedId) setHighlight(null);
      return;
    }
    const ids = g.nodes.filter((n) =>
      n.label.toLowerCase().includes(q)
      || (n.path ?? "").toLowerCase().includes(q)
      || (n.sub ?? "").toLowerCase().includes(q)).map((n) => n.id);
    setHighlight({ nodes: new Set(ids), edges: new Set() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const onDirective = useCallback((d: { node_ids: string[]; mode: string }) => {
    if (!g) return;
    const nodes = new Set(d.node_ids.filter((id) => g.byId.has(id)));
    const edges = new Set<string>();
    if (d.mode === "trace") {
      d.node_ids.forEach((id, i) => {
        if (i > 0) edges.add(`${d.node_ids[i - 1]}>${id}`);
      });
    } else {
      for (const e of g.edges) {
        if (nodes.has(e.from) && nodes.has(e.to)) edges.add(`${e.from}>${e.to}`);
      }
    }
    setHighlight({ nodes, edges, flow: d.mode === "trace" });
  }, [g]);

  const applyTourStep = useCallback((t: Tour, i: number) => {
    setTourIdx(i);
    const step = t.steps[i];
    if (step) onDirective({ node_ids: step.node_ids, mode: step.mode });
  }, [onDirective]);

  async function openTour() {
    if (!ws || tourBusy) return;
    setTourBusy(true);
    setTourError(null);
    try {
      const existing = await api.listTours(ws.id);
      const t = existing[0] ?? await api.generateTour(ws.id);
      setView("map");
      setSelectedId(null);
      setDetail(null);
      setTour(t);
      applyTourStep(t, 0);
    } catch (e) {
      setTourError(e instanceof Error ? e.message : String(e));
    } finally {
      setTourBusy(false);
    }
  }

  const closeTour = () => {
    setTour(null);
    setHighlight(null);
  };

  async function loadDiff(base: string) {
    if (!ws) return;
    setDiffBusy(true);
    try {
      setDiff(await api.getDiff(ws.id, base));
    } catch {
      setDiff(null);
    } finally {
      setDiffBusy(false);
    }
  }

  async function openDiff() {
    if (!ws) return;
    setView("map");
    setDetail(null);
    setSelectedId(null);
    setHighlight(null);
    setDiffOpen(true);
    setDiffBusy(true);
    try {
      let snaps = await api.listSnapshots(ws.id);
      if (snaps.length === 0) {
        await api.createSnapshot(ws.id, { label: "baseline" });
        snaps = await api.listSnapshots(ws.id);
      }
      setSnapshots(snaps);
      await loadDiff(diffBase);
    } finally {
      setDiffBusy(false);
    }
  }

  async function saveBaseline() {
    if (!ws) return;
    setDiffBusy(true);
    try {
      const snap = await api.createSnapshot(ws.id, { label: "baseline" });
      setSnapshots(await api.listSnapshots(ws.id));
      setDiffBase(String(snap.id));
      await loadDiff(String(snap.id));
    } finally {
      setDiffBusy(false);
    }
  }

  const closeDiff = () => {
    setDiffOpen(false);
    setDiff(null);
  };

  async function onExport(format: "svg" | "json") {
    const base = (ws?.name || "onboarder").replace(/[^\w.-]+/g, "-");
    try {
      if (format === "json" && graphRaw) exportJson(base, graphRaw);
      else if (format === "svg") await exportSvg(base);
    } catch (e) {
      setTourError(`Export failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // keep the comparison current as re-analysis refreshes the graph underneath
  useEffect(() => {
    if (diffOpen && ws) void loadDiff(diffBase);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphRaw]);

  const goHome = () => {
    setPhase("home");
    setWs(null);
    setGraphRaw(null);
    localStorage.removeItem("ob_ws");
    void refreshRecents();
  };

  const onNav = (k: RailKey) => {
    if (k === "chat") setView("chat");
    else if (k === "tables") setView("tables");
    else if (k === "infra") { setView("infra"); setDiffOpen(false); }
    else {
      setView("map");
      if (k === "trace") { setSelectedId(null); setDetail(null); setHighlight(null); }
    }
  };

  // ---------- render ----------
  const settingsModal = settingsOpen && (
    <SettingsModal onClose={() => setSettingsOpen(false)} onChanged={setLlmEnabled} />
  );

  if (phase === "home" || !ws) {
    return (
      <>
        <UploadChrome theme={theme} onTheme={toggleTheme} onSettings={() => setSettingsOpen(true)}>
          <UploadEmpty recents={recents} onFiles={handleFiles} onOpen={(w) => void openWorkspace(w.id)} error={uploadError} />
        </UploadChrome>
        {settingsModal}
      </>
    );
  }

  if (phase === "analyzing") {
    return (
      <>
        <UploadChrome theme={theme} onTheme={toggleTheme} onSettings={() => setSettingsOpen(true)}>
          <AnalysisState
            ws={ws}
            onReady={() => { void loadGraph(ws.id).then(() => { setPhase("workspace"); setView("map"); }); }}
          />
        </UploadChrome>
        {settingsModal}
      </>
    );
  }

  if (!g) return null;

  const activeRail: RailKey = view === "chat" ? "chat" : view === "tables" ? "tables"
    : view === "infra" ? "infra" : "map";
  const hasInfra = g.nodes.some((n) => ["infra_compute", "gateway", "queue", "topic", "datastore"].includes(n.raw.kind));
  const showNodePanel = detail && detail.kind !== "table" && view === "map" && !diffOpen;
  const showTable = view === "tables" && detail?.kind === "table";

  return (
    <div className="screen" data-theme={theme === "dark" ? "dark" : undefined}>
      <Rail active={activeRail} onNav={onNav} onHome={goHome} onSettings={() => setSettingsOpen(true)} hasInfra={hasInfra} />
      <TopBar
        ws={ws} projects={projects} theme={theme} onTheme={toggleTheme}
        onReanalyze={() => void reanalyze()} search={search} onSearch={setSearch}
        onTour={() => void openTour()} tourBusy={tourBusy}
        onCompare={() => void openDiff()} compareActive={diffOpen}
        persona={persona} onPersona={setPersona} onExport={(f) => void onExport(f)}
      />
      {view === "chat" ? (
        <MapGraph g={g} highlight={highlight} selectedId={selectedId} showMinimap={false} showZoom={false} showConf={persona === "power"}>
          <div className="chat-scrim" onClick={() => setView("map")} />
          <ChatPanel
            wsId={ws.id} g={g} llmEnabled={llmEnabled}
            onDirective={onDirective}
            onChip={(id) => { setView("map"); void selectById(id); }}
            onClose={() => setView("map")}
            ask={chatAsk}
            onAskConsumed={() => setChatAsk(null)}
          />
        </MapGraph>
      ) : view === "infra" ? (
        <InfraView wsId={ws.id} g={g} llmEnabled={llmEnabled} onClose={() => setView("map")} />
      ) : showTable ? (
        <StarGraph g={g} detail={detail!} onSelect={onSelect}>
          <div className="star-switch">
            {g.nodes.filter((n) => n.type === "table").map((t) => (
              <span key={t.id} className={"chip" + (t.id === detail!.id ? " on" : "")}
                onClick={(e) => { e.stopPropagation(); void selectById(t.id, { toTables: true }); }}>
                {t.label}
              </span>
            ))}
          </div>
          <TablePanel
            wsId={ws.id} g={g} detail={detail!}
            projName={projName.get(detail!.project_id) ?? ""}
            onClose={() => { setView("map"); setDetail(null); setSelectedId(null); setHighlight(null); }}
            onReload={() => void refreshGraph()}
          />
        </StarGraph>
      ) : (
        <MapGraph g={g} highlight={highlight} selectedId={selectedId} onSelect={onSelect}
          showMinimap={!showNodePanel && !tour && !diffOpen} showConf={persona === "power"}>
          {diffOpen && diff && (
            <div className="diff-banner">
              <Icon.diff style={{ width: 13, height: 13 }} />
              Compare mode · vs {diff.base.label}
              <span className="add">+{diff.added_nodes.length + diff.added_edges.length} added</span>
              <span className="del">−{diff.removed_nodes.length + diff.removed_edges.length} removed</span>
              <span className="chg">~{diff.changed_nodes.length} changed</span>
            </div>
          )}
          {diffOpen && (
            <DiffPanel
              g={g} diff={diff} snapshots={snapshots} base={diffBase} busy={diffBusy}
              onBase={(spec) => { setDiffBase(spec); void loadDiff(spec); }}
              onSaveBaseline={() => void saveBaseline()}
              onClose={closeDiff}
              onFocus={(id) => setHighlight({ nodes: new Set([id]), edges: new Set() })}
            />
          )}
          {showNodePanel && (
            <NodePanel
              wsId={ws.id} g={g} detail={detail!} llmEnabled={llmEnabled}
              onClose={() => { setDetail(null); setSelectedId(null); setHighlight(null); }}
              onJump={(id) => void selectById(id)}
              onReload={() => void refreshGraph()}
            />
          )}
          {tour && (
            <TourCard tour={tour} idx={tourIdx} onIdx={(i) => applyTourStep(tour, i)} onClose={closeTour} />
          )}
          {tourError && (
            <div className="tour-card" style={{ borderColor: "var(--writes)" }}>
              <div className="tour-head">
                <span className="tour-eyebrow" style={{ color: "var(--writes)" }}>Tour unavailable</span>
                <button className="panel-close" onClick={() => setTourError(null)}>✕</button>
              </div>
              <div className="tour-narration">{tourError}</div>
            </div>
          )}
        </MapGraph>
      )}
      {settingsModal}
    </div>
  );
}
