import { useMemo, useState, type ReactElement, type ReactNode } from "react";
import { Icon } from "../icons";
import { NODE_H, NODE_W, anchorsFor, curvePath, edgeKey, type DGraph, type DNode } from "../model";
import { NodeCard, type NodeState } from "./NodeCard";

export interface Highlight {
  nodes: Set<string>;
  edges: Set<string>;
  flow?: boolean;
  isolate?: boolean;
}

function Minimap({ g, highlight }: { g: DGraph; highlight: Highlight | null }) {
  const layerColor: Record<string, string> = {
    endpoint: "--l-endpoint", controller: "--l-controller", service: "--l-service",
    repository: "--l-repo", table: "--l-table",
  };
  return (
    <div className="minimap">
      <div className="mm-head"><span>MINIMAP</span><span>{g.nodes.length} nodes</span></div>
      <svg viewBox={`0 0 ${g.stageW} ${g.stageH}`} preserveAspectRatio="xMidYMid meet" style={{ height: 96 }}>
        {g.nodes.map((n) => {
          const on = !highlight || highlight.nodes.has(n.id);
          return (
            <rect key={n.id} x={n.x} y={n.y} width={NODE_W[n.type]} height={NODE_H} rx={6}
              fill={on ? `var(${layerColor[n.type]})` : "var(--line-strong)"} opacity={on ? 0.9 : 0.35} />
          );
        })}
        <rect x={2} y={2} width={g.stageW - 4} height={g.stageH - 4} rx={10}
          fill="none" stroke="var(--brand)" strokeWidth={6} opacity={0.5} />
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
  const dim = !!highlight;

  const edgeEls = useMemo(() => {
    const els = g.edges.map((e, i) => {
      const a = g.byId.get(e.from);
      const b = g.byId.get(e.to);
      if (!a || !b) return null;
      const p1 = anchorsFor(a, "out");
      const p2 = anchorsFor(b, "in");
      const d = curvePath(p1.x, p1.y, p2.x, p2.y);
      const isHl = highlight?.edges.has(edgeKey(e)) ?? false;
      let cls = "edge-base";
      const style: Record<string, number> = {};
      const diffTag = e.raw?.__diff;
      if (diffTag === "added") {
        cls = "edge-diff-add";
      } else if (diffTag === "removed") {
        cls = "edge-diff-del";
      } else if (e.kind === "cross") {
        cls = "edge-cross";
        if (dim && !isHl) style.opacity = 0.35;
      } else if (isHl) {
        cls = "edge-hl" + (highlight?.flow ? " edge-flow" : "");
      } else if (dim) {
        cls = "edge-dim";
      } else if (e.kind === "low") {
        cls = "edge-base edge-low";
      }
      return { el: <path key={i} className={cls} style={style} d={d} />, hl: isHl };
    }).filter((x): x is { el: ReactElement; hl: boolean } => x !== null);
    return els.sort((a, b) => Number(a.hl) - Number(b.hl)).map((o) => o.el);
  }, [g, highlight, dim]);

  const nodeState = (n: DNode): NodeState => {
    if (selectedId === n.id) return "sel";
    if (highlight?.nodes.has(n.id)) return "hl";
    if (dim && !highlight!.nodes.has(n.id)) return "dim";
    return null;
  };

  return (
    <div className="body" onClick={() => onSelect?.(null)}>
      <div className="canvas-grid" />
      <div className="map-scroll">
        <div
          className="map-stage"
          style={{
            width: g.stageW * zoom,
            height: g.stageH * zoom,
          }}
        >
          <div style={{ transform: `scale(${zoom})`, transformOrigin: "0 0", width: g.stageW, height: g.stageH, position: "relative" }}>
            <svg className="edges" width={g.stageW} height={g.stageH} viewBox={`0 0 ${g.stageW} ${g.stageH}`}>
              {edgeEls}
            </svg>
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
            {g.nodes.map((n) => (
              <NodeCard key={n.id} n={n} state={nodeState(n)} onClick={onSelect ?? undefined} showConf={showConf} />
            ))}
          </div>
        </div>
      </div>
      {showMinimap && <Minimap g={g} highlight={highlight} />}
      {showZoom && <ZoomCtl zoom={zoom} onZoom={(z) => setZoom(Math.min(1.6, Math.max(0.5, Number(z.toFixed(2)))))} />}
      {children}
    </div>
  );
}
