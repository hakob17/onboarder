import { useState } from "react";
import { Icon, Logo } from "../icons";
import type { Project, Workspace } from "../api";

export type Persona = "dev" | "pm" | "power";

export type RailKey = "map" | "trace" | "tables" | "infra" | "chat";

export function Rail({ active, onNav, onHome, onSettings, hasInfra }: {
  active: RailKey;
  onNav: (k: RailKey) => void;
  onHome: () => void;
  onSettings: () => void;
  hasInfra: boolean;
}) {
  const items: [RailKey, string][] = [
    ["map", "Map"], ["trace", "Trace"], ["tables", "Tables"],
    ...(hasInfra ? [["infra", "Infrastructure"] as [RailKey, string]] : []),
    ["chat", "Chat"],
  ];
  return (
    <div className="rail">
      <div className="rail-logo" title="Onboarder — projects" onClick={onHome} style={{ cursor: "pointer" }}>
        <Logo />
      </div>
      {items.map(([k, label]) => {
        const Ico = k === "infra" ? Icon.cloud : Icon[k];
        return (
          <div key={k} className={"rail-btn" + (active === k ? " active" : "")} title={label} onClick={() => onNav(k)}>
            <Ico />
          </div>
        );
      })}
      <div className="rail-spacer" />
      <div className="rail-btn" title="Settings" onClick={onSettings}><Icon.settings /></div>
    </div>
  );
}

export function describeProjects(projects: Project[]): string {
  if (!projects.length) return "no projects";
  const stacks = [...new Set(projects.map((p) => p.stack))];
  const files = projects.reduce((s, p) => s + Number(p.stats?.files ?? 0), 0);
  const parts = [stacks.join(" + "), `${files.toLocaleString()} files`];
  if (projects.length > 1) parts.push(`${projects.length} projects`);
  return parts.join(" · ");
}

const PERSONAS: [Persona, string][] = [["dev", "Developer"], ["pm", "Manager"], ["power", "Power"]];

function ExportMenu({ onExport }: { onExport: (f: "svg" | "json") => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <button className="tbtn" title="Export the current view" onClick={() => setOpen((o) => !o)}>
        <Icon.download />Export
      </button>
      {open && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 39 }} onClick={() => setOpen(false)} />
          <div style={{
            position: "absolute", right: 0, top: 38, zIndex: 40, minWidth: 150,
            background: "var(--surface)", border: "1px solid var(--line)",
            borderRadius: "var(--border-radius-md)", boxShadow: "var(--shadow-lg)", padding: 4,
          }}>
            {([["svg", "SVG image"], ["json", "JSON graph"]] as const).map(([f, label]) => (
              <div key={f}
                style={{ padding: "7px 11px", fontSize: 12.5, borderRadius: 6, cursor: "pointer", color: "var(--ink-2)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-3)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                onClick={() => { setOpen(false); onExport(f); }}>
                {label}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function TopBar({ ws, projects, theme, onTheme, onReanalyze, search, onSearch, onTour, tourBusy, onCompare, compareActive, persona, onPersona, onExport }: {
  ws: Workspace;
  projects: Project[];
  theme: string;
  onTheme: () => void;
  onReanalyze: () => void;
  search: string;
  onSearch: (q: string) => void;
  onTour: () => void;
  tourBusy: boolean;
  onCompare: () => void;
  compareActive: boolean;
  persona: Persona;
  onPersona: (p: Persona) => void;
  onExport: (f: "svg" | "json") => void;
}) {
  const stacks = [...new Set(projects.map((p) => p.stack))];
  const files = projects.reduce((s, p) => s + Number(p.stats?.files ?? 0), 0);
  return (
    <div className="topbar">
      <span className="proj-name">{ws.name}</span>
      <span className="badge">
        <b>{stacks.join(" + ") || "unknown"}</b> · {files.toLocaleString()} files
        {projects.length > 1 ? ` · ${projects.length} projects` : ""}
      </span>
      <div className="search">
        <Icon.search />
        <input
          placeholder="Find an endpoint, service, or table…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
        />
        <span className="kbd">⌘K</span>
      </div>
      <div className="topbar-actions">
        <select
          value={persona}
          onChange={(e) => onPersona(e.target.value as Persona)}
          title="Audience — adjusts how much detail the map shows"
          style={{
            height: 32, border: "1px solid var(--line)", borderRadius: 8,
            background: "var(--surface)", color: "var(--ink-2)", fontFamily: "var(--ui)",
            fontSize: 12.5, padding: "0 8px", cursor: "pointer",
          }}
        >
          {PERSONAS.map(([p, label]) => <option key={p} value={p}>{label}</option>)}
        </select>
        <ExportMenu onExport={onExport} />
        <button
          className="tbtn"
          onClick={onCompare}
          title="Compare with a saved baseline"
          style={compareActive ? { borderColor: "var(--brand)", color: "var(--brand-strong)" } : undefined}
        >
          <Icon.diff />Compare
        </button>
        <button className="tbtn" onClick={onTour} disabled={tourBusy} title="AI guided tour">
          <Icon.spark style={{ color: "var(--brand)" }} />{tourBusy ? "Preparing…" : "Tour"}
        </button>
        <button className="tbtn" onClick={onReanalyze}><Icon.refresh />Re-analyze</button>
        <button className="tbtn icon" title="Toggle theme" onClick={onTheme}>
          {theme === "dark" ? <Icon.sun /> : <Icon.moon />}
        </button>
      </div>
    </div>
  );
}
