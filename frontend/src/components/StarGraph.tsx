import { useMemo, type ReactNode } from "react";
import type { NodeDetail } from "../api";
import { NODE_W, curvePath, fileStem, type DGraph, type DNode } from "../model";
import { NodeCard } from "./NodeCard";

interface SpokeService {
  node: DNode;
  ops: ("reads" | "writes")[];
  methods: string[];
  y: number;
}

interface Hub {
  node: DNode;
  y: number;
  services: SpokeService[];
}

/** Build the table-centric star from the table's detail + the full graph. */
export function buildStar(g: DGraph, detail: NodeDetail) {
  const hubs: Hub[] = [];
  const repoIds = new Set<string>();
  for (const e of detail.in_edges) {
    if (e.kind !== "READS" && e.kind !== "WRITES") continue;
    if (!repoIds.has(e.src) && g.byId.get(e.src)) {
      repoIds.add(e.src);
      hubs.push({ node: g.byId.get(e.src)!, y: 0, services: [] });
    }
  }
  for (const hub of hubs) {
    const repoOps = detail.in_edges.filter((e) => e.src === hub.node.id);
    const users = g.edges.filter((e) => e.to === hub.node.id && e.kind === "normal");
    const seen = new Set<string>();
    for (const u of users) {
      const svc = g.byId.get(u.from);
      if (!svc || seen.has(svc.id)) continue;
      seen.add(svc.id);
      const ops = new Set<"reads" | "writes">();
      const methods = new Set<string>();
      for (const e of repoOps) {
        const op = e.kind === "WRITES" ? "writes" : "reads";
        for (const ev of e.evidence ?? []) {
          const stem = fileStem(ev.file);
          const m = ev.snippet?.match(/\.(\w+)\(/);
          if (stem === svc.label) {
            ops.add(op);
            if (m) methods.add(m[1] + "()");
          } else if (stem === hub.node.label) {
            ops.add(op); // declared on the repo: any caller may hit it
            if (m) methods.add(m[1] + "()");
          }
        }
      }
      if (ops.size === 0) ops.add("reads");
      hub.services.push({ node: svc, ops: [...ops], methods: [...methods].slice(0, 2), y: 0 });
    }
    if (hub.services.length === 0) {
      // repo with no known caller — still show the repo spoke
      hub.services = [];
    }
  }
  return hubs;
}

export function StarGraph({ g, detail, onSelect, children }: {
  g: DGraph;
  detail: NodeDetail;
  onSelect?: (n: DNode | null) => void;
  children?: ReactNode;
}) {
  const hubs = useMemo(() => buildStar(g, detail), [g, detail]);
  const table = g.byId.get(detail.id);

  // vertical layout: services stacked left, repos middle, table centered right
  let svcY = 120;
  const SVC_PITCH = 130;
  for (const hub of hubs) {
    for (const s of hub.services) {
      s.y = svcY;
      svcY += SVC_PITCH;
    }
    const ys = hub.services.map((s) => s.y);
    hub.y = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : svcY;
    if (!ys.length) svcY += SVC_PITCH;
  }
  const tableY = hubs.length
    ? hubs.map((h) => h.y).reduce((a, b) => a + b, 0) / hubs.length
    : 280;

  const SVC_X = 96, REPO_X = 392, TABLE_X = 612;
  if (!table) return null;

  const edges: { d: string; cls: string }[] = [];
  const labels: { x: number; y: number; text: string; cls: string }[] = [];
  for (const hub of hubs) {
    for (const s of hub.services) {
      s.ops.forEach((op, oi) => {
        const outY = s.y + 12 + oi * 22;
        const inY = hub.y + 24 + (op === "writes" ? -8 : 8);
        edges.push({
          d: curvePath(SVC_X + NODE_W[s.node.type], outY, REPO_X, inY),
          cls: op === "writes" ? "edge-writes" : "edge-reads",
        });
        labels.push({
          x: REPO_X - 90, y: s.y + 6 + oi * 22,
          text: op, cls: op === "writes" ? "var(--writes)" : "var(--reads)",
        });
      });
    }
    edges.push({
      d: curvePath(REPO_X + 188, hub.y + 24, TABLE_X, tableY + 40),
      cls: "edge-hl edge-flow",
    });
  }

  const stageH = Math.max(860, svcY + 120);

  return (
    <div className="body" onClick={() => onSelect?.(null)}>
      <div className="canvas-grid" />
      <div className="map-scroll">
        <div className="map-stage" style={{ width: 1340, height: stageH }}>
          <svg className="edges" width={1340} height={stageH} viewBox={`0 0 1340 ${stageH}`}>
            {edges.map((e, i) => <path key={i} className={e.cls} d={e.d} />)}
          </svg>
          <NodeCard n={table} state="sel" showCols x={TABLE_X} y={tableY} onClick={onSelect ?? undefined} />
          {hubs.map((hub) => (
            <NodeCard key={hub.node.id} n={hub.node} state="hl" x={REPO_X} y={hub.y} onClick={onSelect ?? undefined} />
          ))}
          {hubs.flatMap((hub) => hub.services.map((s) => (
            <NodeCard key={s.node.id} n={s.node} state="hl" x={SVC_X} y={s.y}
              sub={s.methods.join(" · ") || s.node.sub} onClick={onSelect ?? undefined} />
          )))}
          {labels.map((l, i) => (
            <div key={i} className="edge-label" style={{ left: l.x, top: l.y, color: l.cls }}>{l.text}</div>
          ))}
        </div>
      </div>
      {children}
    </div>
  );
}
