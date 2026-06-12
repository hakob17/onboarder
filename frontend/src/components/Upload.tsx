import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, eventsUrl, type Project, type Workspace } from "../api";
import { Icon, Logo, Spinner } from "../icons";
import { describeProjects } from "./shell";

function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function UploadChrome({ theme, onTheme, onSettings, children }: {
  theme: string;
  onTheme: () => void;
  onSettings: () => void;
  children: ReactNode;
}) {
  return (
    <div className="upload-screen" data-theme={theme === "dark" ? "dark" : undefined}>
      <div className="upload-top">
        <div className="upload-brand">
          <div className="rail-logo" style={{ margin: 0 }}><Logo /></div>
          <span style={{ fontWeight: 600, fontSize: 15 }}>Onboarder</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="tbtn icon" title="Settings" onClick={onSettings}><Icon.settings /></button>
          <button className="tbtn icon" title="Toggle theme" onClick={onTheme}>
            {theme === "dark" ? <Icon.sun /> : <Icon.moon />}
          </button>
        </div>
      </div>
      <div className="upload-stage">{children}</div>
    </div>
  );
}

export function UploadEmpty({ recents, onFiles, onOpen, error }: {
  recents: Workspace[];
  onFiles: (files: File[]) => void;
  onOpen: (ws: Workspace) => void;
  error?: string | null;
}) {
  const [hot, setHot] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pick = (list: FileList | null) => {
    const files = [...(list ?? [])].filter((f) => f.name.toLowerCase().endsWith(".zip"));
    if (files.length) onFiles(files);
  };
  return (
    <div className="upload-col">
      <div
        className={"upload-drop" + (hot ? " hot" : "")}
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setHot(true); }}
        onDragLeave={() => setHot(false)}
        onDrop={(e) => { e.preventDefault(); setHot(false); pick(e.dataTransfer.files); }}
      >
        <div className="drop-icon"><Icon.upload /></div>
        <div className="drop-title">Drop a project <span className="mono">.zip</span> to map it</div>
        <div className="drop-sub">We statically analyze the source — we never execute your code.</div>
        <button className="drop-btn" onClick={(e) => { e.stopPropagation(); fileRef.current?.click(); }}>
          <Icon.zip />Browse files
        </button>
        <div className="drop-multi">
          <Icon.link style={{ width: 13, height: 13 }} />
          Drop several zips together to map cross-project calls
        </div>
        <input
          ref={fileRef} type="file" accept=".zip" multiple style={{ display: "none" }}
          onChange={(e) => { pick(e.target.files); e.target.value = ""; }}
        />
      </div>
      {error && (
        <div className="ai-note" style={{ color: "var(--writes)", textAlign: "center" }}>{error}</div>
      )}

      {recents.length > 0 && (
        <div className="recents">
          <div className="recents-head">Recent projects</div>
          {recents.slice(0, 4).map((w) => (
            <div key={w.id} className="recent-row" onClick={() => onOpen(w)}>
              <div className="recent-ico"><Icon.zip /></div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="recent-name">{w.name}</div>
                <div className="recent-meta">{describeProjects(w.projects ?? [])}</div>
              </div>
              {(w.projects?.length ?? w.project_count ?? 0) > 1 && (
                <span className="recent-link"><Icon.link style={{ width: 11, height: 11 }} />{w.projects?.length ?? w.project_count} projects</span>
              )}
              <span className="recent-when">{timeAgo(w.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const STEPS = ["Extract", "Parse files", "Resolve edges", "Build graph", "AI summaries"];

interface LogLine {
  text: string;
  cls: "" | "ok" | "live";
}

export function AnalysisState({ ws, onReady }: { ws: Workspace; onReady: () => void }) {
  const [projects, setProjects] = useState<Project[]>(ws.projects ?? []);
  const [fileCount, setFileCount] = useState(0);
  const [log, setLog] = useState<LogLine[]>([{ text: "extracting archives…", cls: "live" }]);
  const doneRef = useRef(false);

  const pushLog = (line: LogLine) =>
    setLog((ls) => [...ls.map((l) => ({ ...l, cls: l.cls === "live" ? ("" as const) : l.cls })), line].slice(-7));

  useEffect(() => {
    const es = new EventSource(eventsUrl(ws.id));
    es.addEventListener("analysis_started", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      pushLog({ text: `analyzing ${d.project_id} (${d.payload?.stack ?? "?"})`, cls: "live" });
    });
    es.addEventListener("files_scanned", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      setFileCount((c) => Math.max(c, Number(d.payload?.count ?? 0)));
      pushLog({ text: `parsed ${d.payload?.count} files…`, cls: "live" });
    });
    es.addEventListener("analysis_completed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      pushLog({ text: `✓ ${d.project_id}: ${d.payload?.nodes ?? 0} nodes · ${d.payload?.edges ?? 0} edges · ${d.payload?.files ?? 0} files`, cls: "ok" });
      refresh();
    });
    es.addEventListener("analysis_failed", (e) => {
      const d = JSON.parse((e as MessageEvent).data);
      pushLog({ text: `✗ ${d.project_id}: ${d.payload?.error ?? "failed"}`, cls: "" });
      refresh();
    });
    const poll = setInterval(refresh, 2500);
    async function refresh() {
      try {
        const ps = await api.listProjects(ws.id);
        setProjects(ps);
      } catch { /* transient */ }
    }
    refresh();
    return () => { es.close(); clearInterval(poll); };
  }, [ws.id]);

  const total = projects.length || 1;
  const ready = projects.filter((p) => p.status === "ready").length;
  const failed = projects.filter((p) => p.status === "failed").length;
  const allDone = projects.length > 0 && ready + failed === total;

  useEffect(() => {
    if (allDone && !doneRef.current) {
      doneRef.current = true;
      setTimeout(onReady, ready > 0 ? 900 : 1800);
    }
  }, [allDone]);

  const scanning = projects.some((p) => p.status === "analyzing") || (!allDone && fileCount > 0);
  const stepState = (i: number): "done" | "active" | "" => {
    if (i === 0) return "done";
    if (allDone) return "done";
    if (i === 1) return scanning ? "active" : fileCount > 0 ? "done" : "active";
    if (i === 2) return fileCount > 0 && scanning ? "active" : ready > 0 ? "done" : "";
    if (i === 3) return ready > 0 ? "done" : scanning ? "active" : "";
    return "";
  };
  const progress = allDone ? 100 : Math.min(95, (ready / total) * 70 + (scanning ? 20 : 5));
  const totalFiles = projects.reduce((s, p) => s + Number(p.stats?.files ?? 0), 0) || fileCount;
  const stacks = [...new Set(projects.map((p) => p.stack))].join(" + ");

  return (
    <div className="analysis-col">
      <div className="analysis-head">
        <Spinner />
        <div>
          <div className="an-title">Analyzing <span className="mono">{ws.name}</span></div>
          <div className="an-sub">{stacks || "detecting stack"} · {total} project{total === 1 ? "" : "s"}{totalFiles ? ` · ${totalFiles.toLocaleString()} files` : ""}</div>
        </div>
      </div>

      <div className="stepper">
        {STEPS.map((label, i) => {
          const st = stepState(i);
          return (
            <div key={label} className={"step " + st}>
              <div className="step-dot">
                {st === "done" ? <Icon.check style={{ width: 12, height: 12 }} />
                  : st === "active" ? <span className="pulse" /> : null}
              </div>
              <div className="step-label">{label}</div>
              {i === 1 && st === "active" && fileCount > 0 && (
                <span className="step-spark mono">{fileCount.toLocaleString()} files</span>
              )}
              {i === 4 && <span className="step-spark">generated on demand</span>}
            </div>
          );
        })}
      </div>

      <div className="progress-track"><div className="progress-fill" style={{ width: `${progress}%` }} /></div>

      <div className="log-box mono">
        {log.map((l, i) => <div key={i} className={"log-line " + l.cls}>{l.text}</div>)}
      </div>
    </div>
  );
}
