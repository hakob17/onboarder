import { useEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import { Icon } from "../icons";
import {
  NODE_H, NODE_W, curvePath, edgeKey, relayout,
  type DGraph, type DGroup, type DNode, type LayerKind,
} from "../model";
import { NodeCard, type NodeState } from "./NodeCard";

export interface Highlight {
  nodes: Set<string>;
  edges: Set<string>;
  flow?: boolean;
  isolate?: boolean;
}

interface Rect { x: number; y: number; w: number; h: number; group: boolean }

const defaultCollapsed = (g: DGraph) => new Set(g.groups.filter((gr) => gr.collapsible).map((gr) => gr.id));

function Minimap({ g, groups, pos, highlight }: {
  g: DGraph; groups: DGroup[]; pos: Map<string, { x: number; y: number }>; highlight: Highlight | null;
}) {
  const layerColor: Record<string, string> = {
    endpoint: "--l-endpoint", controller: "--l-controller", service: "--l-service",
    repository: "--l-repo", graphql: "--l-graphql", table: "--l-table", messaging: "--l-messaging",
  };
  const stageW = Math.max(1000, ...groups.map((gr) => gr.x + gr.w), ...[...pos.values()].map((p) => p.x + 188));
  const stageH = Math.max(680, ...groups.map((gr) => gr.y + gr.h), ...[...pos.values()].map((p) => p.y + NODE_H));
  const visible = g.nodes.filter((n) => pos.has(n.id));
  return (
    <div className="minimap">
      <div className="mm-head"><span>MINIMAP</span><span>{g.nodes.length} nodes</span></div>
      <svg viewBox={`0 0 ${stageW} ${stageH}`} preserveAspectRatio="xMidYMid meet" style={{ height: 96 }}>
        {groups.filter((gr) => gr.collapsed).map((gr) => (
          <rect key={gr.id} x={gr.x} y={gr.y} width={gr.w} height={gr.h} rx={8}
            fill={`var(${layerColor[gr.col]})`} opacity={0.8} />
        ))}
        {visible.map((n) => {
          const p = pos.get(n.id)!;
          const on = !highlight || highlight.nodes.has(n.id);
          return <rect key={n.id} x={p.x} y={p.y} width={NODE_W[n.type]} height={NODE_H} rx={6}
            fill={on ? `var(${layerColor[n.type]})` : "var(--line-strong)"} opacity={on ? 0.9 : 0.35} />;
        })}
      </svg>
    </div>
  );
}

function ZoomCtl({ zoom, onZoom }: { zoom: number; onZoom: (z: number) => void }) {
  return (
    <div className="zoomctl">
      <button onClick={() => onZoom(zoom + 0.1)} title="Zoom in"><Icon.plus /></button>
      <div className="zoom-val">{Math.round(zoom * 100)}%</div>
      <button onClick={() => onZoom(zoom - 0.1)} title="Zoom out"><Icon.minus /></button>
      <button onClick={() => onZoom(1)} title="Reset"><Icon.fit /></button>
    </div>
  );
}

// A collapsed package: a whole folder of classes shown as one card you can open.
function GroupCard({ gr, hue, dim, hot, onOpen }: {
  gr: DGroup; hue: string; dim: boolean; hot: boolean; onOpen: () => void;
}) {
  const n = gr.memberIds.length;
  return (
    <button className={"grp" + (hot ? " hot" : "") + (dim ? " dim" : "")}
      style={{ left: gr.x, top: gr.y, width: gr.w, height: gr.h }}
      title={`${gr.title} — ${n} items, click to expand`}
      onClick={(e) => { e.stopPropagation(); onOpen(); }}>
      <span className="grp-bar" style={{ background: `var(${hue})` }} />
      <span className="grp-body">
        <span className="grp-label">{gr.label}</span>
        <span className="grp-meta">{n} items</span>
      </span>
      <span className="grp-stack" aria-hidden>
        {Array.from({ length: Math.min(4, n) }).map((_, i) => (
          <span key={i} style={{ background: `var(${hue})`, opacity: 0.25 + i * 0.12 }} />
        ))}
      </span>
      <Icon.plus className="grp-chev" style={{ width: 13, height: 13 }} />
    </button>
  );
}

export function MapGraph({ g, highlight, selectedId, onSelect, showMinimap = true, showZoom = true, showConf = false, children }: {
  g: DGraph;
  highlight: Highlight | null;
  selectedId?: string | null;
  onSelect?: (n: DNode | null) => void;
  showMinimap?: boolean;
  showZoom?: boolean;
  showConf?: boolean;
  children?: ReactNode;
}) {
  const [zoom, setZoom] = useState(1);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => defaultCollapsed(g));
  useEffect(() => { setCollapsed(defaultCollapsed(g)); }, [g]);

  const dim = !!highlight;
  const hueOf = useMemo(() => new Map(g.cols.map((c) => [c.id as LayerKind, c.hue])), [g]);
  const collapsibleCount = useMemo(() => g.groups.filter((gr) => gr.collapsible).length, [g]);

  // a selected/searched node forces its package open so the match is actually visible
  const forceOpen = useMemo(() => {
    const s = new Set<string>();
    const mark = (id: string) => { const n = g.byId.get(id); if (n?.group) s.add(n.group); };
    if (selectedId) mark(selectedId);
    if (highlight) highlight.nodes.forEach(mark);
    return s;
  }, [g, highlight, selectedId]);

  const effCollapsed = useMemo(() => {
    const s = new Set(collapsed);
    forceOpen.forEach((id) => s.delete(id));
    return s;
  }, [collapsed, forceOpen]);

  const L = useMemo(() => relayout(g, effCollapsed), [g, effCollapsed]);
  const stageW = L.stageW, stageH = L.stageH;

  const toggle = (gid: string) => setCollapsed((prev) => {
    const s = new Set(prev);
    if (s.has(gid)) s.delete(gid); else s.add(gid);
    return s;
  });

  // Resolve every edge endpoint to what's actually on screen — its own node, or the
  // collapsed package card standing in for it — then aggregate so module-to-module
  // traffic reads as one wire instead of a hairball.
  const { groupWires, nodeEdges } = useMemo(() => {
    const collapsedGroupBox = new Map<string, DGroup>();
    for (const gr of L.groups) if (gr.collapsed) collapsedGroupBox.set(gr.id, gr);
    const vkey = (id: string): string | null => {
      const n = g.byId.get(id);
      if (!n) return null;
      if (n.group && collapsedGroupBox.has(n.group)) return n.group;
      return L.pos.has(id) ? id : null;
    };
    const rectOf = (key: string): Rect | null => {
      const gr = collapsedGroupBox.get(key);
      if (gr) return { x: gr.x, y: gr.y, w: gr.w, h: gr.h, group: true };
      const n = g.byId.get(key); const p = L.pos.get(key);
      if (!n || !p) return null;
      return { x: p.x, y: p.y, w: NODE_W[n.type], h: NODE_H, group: false };
    };

    type Agg = { from: string; to: string; count: number; hot: boolean };
    const agg = new Map<string, Agg>();
    for (const e of g.edges) {
      const vf = vkey(e.from), vt = vkey(e.to);
      if (!vf || !vt || vf === vt) continue;
      const k = `${vf}>${vt}`;
      let a = agg.get(k);
      if (!a) { a = { from: vf, to: vt, count: 0, hot: false }; agg.set(k, a); }
      a.count++;
      if (highlight?.edges.has(edgeKey(e))) a.hot = true;
    }

    const groupWires: { el: ReactElement; mid: { x: number; y: number }; count: number; hot: boolean; id: string }[] = [];
    const nodeEdges: { el: ReactElement; hl: boolean }[] = [];
    let i = 0;
    for (const a of agg.values()) {
      const ra = rectOf(a.from), rb = rectOf(a.to);
      if (!ra || !rb) continue;
      const fwd = rb.x >= ra.x;
      const p1 = { x: fwd ? ra.x + ra.w : ra.x, y: ra.y + ra.h / 2 };
      const p2 = { x: fwd ? rb.x : rb.x + rb.w, y: rb.y + rb.h / 2 };
      const d = curvePath(p1.x, p1.y, p2.x, p2.y);
      const isGroupWire = ra.group || rb.group;
      i++;
      if (isGroupWire) {
        const w = Math.min(7, 1.5 + Math.log2(a.count + 1) * 1.4);
        groupWires.push({
          id: `${a.from}>${a.to}`, count: a.count, hot: a.hot,
          mid: { x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 },
          el: <path key={`gw${i}`} className={"grp-wire" + (a.hot ? " hot" : "") + (dim && !a.hot ? " dim" : "")}
            d={d} style={{ strokeWidth: w }} />,
        });
      } else {
        const isHl = a.hot;
        let cls = "edge-base";
        const style: Record<string, number> = {};
        if (dim && !isHl) cls = "edge-dim";
        else if (isHl) cls = "edge-hl" + (highlight?.flow ? " edge-flow" : "");
        nodeEdges.push({ el: <path key={`ne${i}`} className={cls} style={style} d={d} />, hl: isHl });
      }
    }
    nodeEdges.sort((x, y) => Number(x.hl) - Number(y.hl));
    return { groupWires, nodeEdges };
  }, [g, L, highlight, dim]);

  const nodeState = (n: DNode): NodeState => {
    if (selectedId === n.id) return "sel";
    if (highlight?.nodes.has(n.id)) return "hl";
    if (dim && !highlight!.nodes.has(n.id)) return "dim";
    return null;
  };

  const visibleNodes = useMemo(() => g.nodes.filter((n) => L.pos.has(n.id)), [g, L]);

  // When a node is selected, scroll it toward the left so its outgoing wires and the
  // nodes it calls land in the visible area beside the detail panel (which overlays the right).
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!selectedId) return;
    const sc = scrollRef.current;
    if (!sc) return;
    const raf = requestAnimationFrame(() => {
      const el = sc.querySelector(".node.sel") as HTMLElement | null;
      if (!el) return;
      const er = el.getBoundingClientRect(), sr = sc.getBoundingClientRect();
      sc.scrollTo({
        left: Math.max(0, sc.scrollLeft + (er.left - sr.left) - sc.clientWidth * 0.16),
        top: Math.max(0, sc.scrollTop + (er.top - sr.top) - sc.clientHeight * 0.38),
        behavior: "smooth",
      });
    });
    return () => cancelAnimationFrame(raf);
  }, [selectedId, L]);

  return (
    <div className="body" onClick={() => onSelect?.(null)}>
      <div className="canvas-grid" />
      {collapsibleCount > 0 && (
        <div className="grp-toolbar" onClick={(e) => e.stopPropagation()}>
          <Icon.repos style={{ width: 13, height: 13, color: "var(--ink-3)" }} />
          <span className="grp-toolbar-label">Grouped by package</span>
          <button className="tbtn sm" onClick={() => setCollapsed(new Set())}>Expand all</button>
          <button className="tbtn sm" onClick={() => setCollapsed(defaultCollapsed(g))}>Collapse all</button>
        </div>
      )}
      <div className="map-scroll" ref={scrollRef}>
        <div className="map-stage" style={{ width: stageW * zoom, height: stageH * zoom }}>
          <div style={{ transform: `scale(${zoom})`, transformOrigin: "0 0", width: stageW, height: stageH, position: "relative" }}>
            <svg className="edges" width={stageW} height={stageH} viewBox={`0 0 ${stageW} ${stageH}`}>
              {nodeEdges.map((o) => o.el)}
              {groupWires.map((o) => o.el)}
            </svg>
            {groupWires.filter((w) => w.count > 1).map((w) => (
              <span key={w.id} className={"grp-wire-pill" + (w.hot ? " hot" : "") + (dim && !w.hot ? " dim" : "")}
                style={{ left: w.mid.x - 11, top: w.mid.y - 9 }}>{w.count}</span>
            ))}
            {g.cols.map((c) => {
              const cnt = g.nodes.filter((n) => n.type === c.id).length;
              return (
                <div key={c.id} className="col-head" style={{ position: "absolute", left: c.x + 2, top: 14 }}>
                  <span className="dot" style={{ background: `var(${c.hue})` }} />
                  {c.label}
                  <span className="count">{cnt}</span>
                </div>
              );
            })}
            {/* expanded-package shells (behind their member cards) */}
            {L.groups.filter((gr) => !gr.collapsed).map((gr) => (
              <div key={gr.id} className="grp-open" style={{ left: gr.x, top: gr.y, width: gr.w, height: gr.h }}
                onClick={(e) => e.stopPropagation()}>
                <button className="grp-open-head" title={gr.title} onClick={() => toggle(gr.id)}>
                  <span className="grp-bar" style={{ background: `var(${hueOf.get(gr.col)})` }} />
                  <span className="grp-label">{gr.label}</span>
                  <span className="grp-meta">{gr.memberIds.length}</span>
                  <Icon.minus className="grp-chev" style={{ width: 13, height: 13 }} />
                </button>
              </div>
            ))}
            {/* collapsed package cards */}
            {L.groups.filter((gr) => gr.collapsed).map((gr) => (
              <GroupCard key={gr.id} gr={gr} hue={hueOf.get(gr.col) ?? "--l-service"}
                dim={dim} hot={!!highlight && gr.memberIds.some((id) => highlight.nodes.has(id))}
                onOpen={() => toggle(gr.id)} />
            ))}
            {visibleNodes.map((n) => {
              const p = L.pos.get(n.id)!;
              return <NodeCard key={n.id} n={n} state={nodeState(n)} onClick={onSelect ?? undefined}
                showConf={showConf} x={p.x} y={p.y} />;
            })}
          </div>
        </div>
      </div>
      {showMinimap && <Minimap g={g} groups={L.groups} pos={L.pos} highlight={highlight} />}
      {showZoom && <ZoomCtl zoom={zoom} onZoom={(z) => setZoom(Math.min(1.6, Math.max(0.5, Number(z.toFixed(2)))))} />}
      {children}
    </div>
  );
}
