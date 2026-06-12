import { Icon, Logo } from "../icons";
import type { Project, Workspace } from "../api";

export type RailKey = "map" | "trace" | "tables" | "chat";

export function Rail({ active, onNav, onHome, onSettings }: {
  active: RailKey;
  onNav: (k: RailKey) => void;
  onHome: () => void;
  onSettings: () => void;
}) {
  const items: [RailKey, string][] = [["map", "Map"], ["trace", "Trace"], ["tables", "Tables"], ["chat", "Chat"]];
  return (
    <div className="rail">
      <div className="rail-logo" title="Onboarder — projects" onClick={onHome} style={{ cursor: "pointer" }}>
        <Logo />
      </div>
      {items.map(([k, label]) => {
        const Ico = Icon[k];
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

export function TopBar({ ws, projects, theme, onTheme, onReanalyze, search, onSearch, onTour, tourBusy, onCompare, compareActive }: {
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
