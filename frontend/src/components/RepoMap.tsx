import { useMemo, useState } from "react";
import type { RepoLink, RepoNode, RepoOverview } from "../api";
import { Icon } from "../icons";
import { inVsCode, openInEditor } from "../vscode";

const RW = 208;
const RH = 80;
const COL_W = 316;
const ROW_H = 120;
const PAD_X = 52;
const PAD_Y = 48;

// Stack identity: label + an existing layer hue, so repos read in the app's palette.
const STACK: Record<string, { label: string; hue: string }> = {
  spring: { label: "Spring", hue: "--l-service" },
  java: { label: "Java", hue: "--l-service" },
  express: { label: "Node", hue: "--l-repo" },
  node: { label: "Node", hue: "--l-repo" },
  nestjs: { label: "NestJS", hue: "--l-repo" },
  android: { label: "Android", hue: "--l-table" },
  fastapi: { label: "FastAPI", hue: "--l-controller" },
  flask: { label: "Flask", hue: "--l-controller" },
  django: { label: "Django", hue: "--l-controller" },
  go: { label: "Go", hue: "--l-endpoint" },
  php: { label: "PHP", hue: "--l-controller" },
};
function stackOf(s: string) {
  return STACK[s] ?? { label: s || "repo", hue: "--l-endpoint" };
}
// Undirected pair = shared data only (no calls either way): draw it as a dashed data wire.
const isData = (l: RepoLink) => !l.directed;

interface Placed extends RepoNode { x: number; y: number; col: number }
type Side = "l" | "r" | "t" | "b";

// Leave each box from the edge that faces the other box, so same-column pairs connect
// vertically instead of looping out to the side.
function anchors(a: Placed, b: Placed) {
  const acx = a.x + RW / 2, acy = a.y + RH / 2, bcx = b.x + RW / 2, bcy = b.y + RH / 2;
  const dx = bcx - acx, dy = bcy - acy;
  let p1: { x: number; y: number }, p2: { x: number; y: number }, d1: Side, d2: Side;
  if (Math.abs(dx) >= Math.abs(dy)) {
    if (dx >= 0) { p1 = { x: a.x + RW, y: acy }; d1 = "r"; p2 = { x: b.x, y: bcy }; d2 = "l"; }
    else { p1 = { x: a.x, y: acy }; d1 = "l"; p2 = { x: b.x + RW, y: bcy }; d2 = "r"; }
  } else {
    if (dy >= 0) { p1 = { x: acx, y: a.y + RH }; d1 = "b"; p2 = { x: bcx, y: b.y }; d2 = "t"; }
    else { p1 = { x: acx, y: a.y }; d1 = "t"; p2 = { x: bcx, y: b.y + RH }; d2 = "b"; }
  }
  return { p1, p2, d1, d2 };
}
function ctrl(p: { x: number; y: number }, d: Side, off: number) {
  if (d === "r") return { x: p.x + off, y: p.y };
  if (d === "l") return { x: p.x - off, y: p.y };
  if (d === "b") return { x: p.x, y: p.y + off };
  return { x: p.x, y: p.y - off };
}
// `bow` lifts a multi-column wire out of the straight line between the two repos so it
// clears any repo sitting in a column it spans over (otherwise it reads as connecting to it).
function wire(a: Placed, b: Placed, bow = 0) {
  const { p1, p2, d1, d2 } = anchors(a, b);
  const off = Math.max(42, Math.hypot(p2.x - p1.x, p2.y - p1.y) * 0.34);
  const c1 = ctrl(p1, d1, off), c2 = ctrl(p2, d2, off);
  if (bow) { c1.y += bow; c2.y += bow; }
  const d = `M${p1.x},${p1.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${p2.x},${p2.y}`;
  const mid = {
    x: 0.125 * p1.x + 0.375 * c1.x + 0.375 * c2.x + 0.125 * p2.x,
    y: 0.125 * p1.y + 0.375 * c1.y + 0.375 * c2.y + 0.125 * p2.y,
  };
  return { d, mid };
}

export function RepoMap({ overview, onOpenRepo }: {
  overview: RepoOverview;
  onOpenRepo: (projectId: string, nodeId?: string) => void;
}) {
  const [selLink, setSelLink] = useState<RepoLink | null>(null);

  const { placed, byId, stageW, stageH } = useMemo(() => {
    const srcs = new Set(overview.links.map((l) => l.src_project));
    const dsts = new Set(overview.links.map((l) => l.dst_project));
    // callers on the left, pure callees on the right, both-in-the-middle; unlinked repos trail right.
    const colOf = (id: string): number => {
      const s = srcs.has(id), d = dsts.has(id);
      if (s && !d) return 0;
      if (s && d) return 1;
      if (!s && d) return 2;
      return 3;
    };
    const cols: Record<number, RepoNode[]> = {};
    for (const p of overview.projects) (cols[colOf(p.id)] ??= []).push(p);
    const colKeys = Object.keys(cols).map(Number).sort((a, b) => a - b);
    const maxRowsLocal = Math.max(1, ...colKeys.map((c) => cols[c].length));
    const placed: Placed[] = [];
    colKeys.forEach((c, ci) => {
      // center each column vertically so short columns sit mid-stage, not top-aligned
      const top = PAD_Y + ((maxRowsLocal - cols[c].length) * ROW_H) / 2;
      cols[c].forEach((p, ri) => placed.push({ ...p, col: ci, x: PAD_X + ci * COL_W, y: top + ri * ROW_H }));
    });
    const byId = new Map(placed.map((p) => [p.id, p]));
    const maxRows = Math.max(1, ...colKeys.map((c) => cols[c].length));
    return {
      placed, byId,
      stageW: PAD_X * 2 + Math.max(1, colKeys.length) * COL_W,
      stageH: Math.max(360, PAD_Y * 2 + maxRows * ROW_H),
    };
  }, [overview]);

  const geom = useMemo(() => overview.links.map((l) => {
    const a = byId.get(l.src_project), b = byId.get(l.dst_project);
    if (!a || !b) return null;
    const span = Math.abs(b.col - a.col);
    // only wires that jump over a column need a detour; bow toward the nearer stage edge
    const midY = (a.y + b.y) / 2 + RH / 2;
    const dir = midY < stageH / 2 ? -1 : 1;
    const bow = span >= 2 ? dir * (RH / 2 + 34) * (span - 1) : 0;
    return { l, ...wire(a, b, bow) };
  }).filter((x): x is { l: RepoLink; d: string; mid: { x: number; y: number } } => x !== null),
    [overview, byId, stageH]);

  return (
    <div className="body repo-body" onClick={() => setSelLink(null)}>
      <div className="canvas-grid" />
      <div className="map-scroll">
        <div className="map-stage" style={{ width: stageW, height: stageH }}>
          <svg className="edges" width={stageW} height={stageH} viewBox={`0 0 ${stageW} ${stageH}`}>
            <defs>
              <marker id="repo-arrow" viewBox="0 0 10 10" refX="8.5" refY="5"
                markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
              </marker>
            </defs>
            {geom.map(({ l, d }, i) => {
              const data = isData(l);
              const on = selLink === l;
              const w = Math.min(7, 1.6 + Math.log2(l.count + 1) * 1.5);
              const color = data ? "var(--l-table)" : "var(--brand)";
              return (
                <g key={i} onClick={(e) => { e.stopPropagation(); setSelLink(l); }} style={{ cursor: "pointer" }}>
                  <path d={d} fill="none" stroke={color} strokeWidth={w}
                    strokeOpacity={on ? 0.95 : 0.42}
                    strokeDasharray={data ? "2 7" : undefined} strokeLinecap="round"
                    markerEnd={data ? undefined : "url(#repo-arrow)"} />
                  <path d={d} fill="none" stroke="transparent" strokeWidth={18} />
                </g>
              );
            })}
          </svg>

          {/* wire labels (count + kind) sitting on the curve */}
          {geom.map(({ l, mid }, i) => {
            const data = isData(l);
            return (
              <button key={`lbl${i}`} className={"wire-pill" + (selLink === l ? " on" : "")}
                style={{ left: mid.x - 30, top: mid.y - 12, borderColor: data ? "var(--l-table)" : "var(--brand)" }}
                onClick={(e) => { e.stopPropagation(); setSelLink(l); }}>
                {data ? <Icon.db style={{ width: 11, height: 11 }} /> : <Icon.link style={{ width: 11, height: 11 }} />}
                {l.count}
              </button>
            );
          })}

          {placed.map((p) => {
            const st = stackOf(p.stack);
            const ep = p.counts.entry_point ?? 0;
            const tbl = p.counts.table ?? 0;
            const ready = p.status === "ready";
            return (
              <button key={p.id} className="repo-node" style={{ left: p.x, top: p.y, width: RW, height: RH }}
                onClick={(e) => { e.stopPropagation(); onOpenRepo(p.id); }}>
                <span className="repo-stack" style={{ background: `var(${st.hue})` }} />
                <div className="repo-main">
                  <div className="repo-name">{p.name}</div>
                  <div className="repo-sub">
                    {!ready
                      ? <span className="repo-analyzing"><Icon.refresh style={{ width: 11, height: 11 }} />{p.status}…</span>
                      : <><span className="repo-stacklabel">{st.label}</span>{ep ? ` · ${ep} endpoints` : ` · ${p.total} nodes`}{tbl ? ` · ${tbl} tables` : ""}</>}
                  </div>
                </div>
                <Icon.arrow className="repo-open" style={{ width: 14, height: 14 }} />
              </button>
            );
          })}
        </div>
      </div>

      {selLink && (
        <WirePanel link={selLink} byId={byId} onOpenRepo={onOpenRepo} onClose={() => setSelLink(null)} />
      )}
    </div>
  );
}

function WirePanel({ link, byId, onOpenRepo, onClose }: {
  link: RepoLink;
  byId: Map<string, Placed>;
  onOpenRepo: (projectId: string, nodeId?: string) => void;
  onClose: () => void;
}) {
  const nameOf = (id: string) => byId.get(id)?.name ?? id;
  const src = byId.get(link.src_project);
  const dst = byId.get(link.dst_project);
  const data = isData(link);
  return (
    <div className="panel" onClick={(e) => e.stopPropagation()}>
      <div className="panel-head">
        <div className="panel-eyebrow">
          {data ? "SHARED DATA" : "INTEGRATION"} · {link.count} connection{link.count === 1 ? "" : "s"}
          <button className="panel-close" onClick={onClose}><Icon.x /></button>
        </div>
        <div className="panel-title" style={{ fontSize: 15 }}>
          {src?.name}
          <Icon.arrow style={{ width: 14, height: 14, margin: "0 2px", color: "var(--ink-3)" }} />
          {dst?.name}
        </div>
        <div style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 4 }}>
          {Object.entries(link.kinds).map(([k, n]) => `${n} ${k.replace(/_/g, " ").toLowerCase()}`).join(" · ")}
          {link.confirmed ? " · confirmed" : ""}
        </div>
      </div>
      <div className="panel-body">
        <div className="sec-label">Connections</div>
        <div className="col-list">
          {link.connections.map((c, i) => {
            const cData = c.kind === "SHARED_TABLE";
            return (
              <div key={i} className="wire-conn">
                <button className="wire-side" title={`${c.src_name} — open ${nameOf(c.src_project)}`}
                  onClick={() => onOpenRepo(c.src_project, c.src)}>
                  <span className="wire-repo">{nameOf(c.src_project)}</span>
                  <span className="wire-nodename">
                    <span className="wire-kindbadge">{c.src_kind.replace(/_/g, " ")}</span>
                    <span className="wire-truncate">{c.src_name}</span>
                  </span>
                  {c.src_file && inVsCode && (
                    <span className="wire-file" onClick={(e) => { e.stopPropagation(); openInEditor(c.src_project, c.src_file!, c.src_line ?? 1); }}>
                      {c.src_file.split("/").pop()}:{c.src_line ?? 1}
                    </span>
                  )}
                </button>
                <Icon.arrow style={{ width: 13, height: 13, color: cData ? "var(--l-table)" : "var(--brand)", flex: "none" }} />
                <button className="wire-side right" title={`${c.dst_name} — open ${nameOf(c.dst_project)}`}
                  onClick={() => onOpenRepo(c.dst_project, c.dst)}>
                  <span className="wire-repo">{nameOf(c.dst_project)}</span>
                  <span className="wire-nodename">
                    <span className="wire-kindbadge">{c.dst_kind.replace(/_/g, " ")}</span>
                    <span className="wire-truncate">{c.dst_name}</span>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
