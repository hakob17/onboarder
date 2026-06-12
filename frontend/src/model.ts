import type { Graph, GraphEdge, GraphNode, Project } from "./api";

export type LayerKind = "endpoint" | "controller" | "service" | "repository" | "table";
export type EdgeKind = "normal" | "reads" | "writes" | "cross" | "low";

export interface DNode {
  id: string;
  type: LayerKind;
  label: string;
  sub: string;
  method?: string;
  path?: string;
  proj: string;
  cross?: boolean;
  foreign?: boolean;
  infra?: string;
  cols?: string[];
  x: number;
  y: number;
  raw: GraphNode;
}

export interface DEdge {
  from: string;
  to: string;
  kind: EdgeKind;
  raw?: GraphEdge;
}

export interface DCol {
  id: LayerKind;
  label: string;
  x: number;
  hue: string;
}

export interface DGraph {
  nodes: DNode[];
  edges: DEdge[];
  byId: Map<string, DNode>;
  cols: DCol[];
  links: GraphEdge[];
  stageW: number;
  stageH: number;
}

const LAYER_ORDER: LayerKind[] = ["endpoint", "controller", "service", "repository", "table"];
const LAYER_META: Record<LayerKind, { label: string; hue: string }> = {
  endpoint: { label: "Endpoints", hue: "--l-endpoint" },
  controller: { label: "Controllers", hue: "--l-controller" },
  service: { label: "Services", hue: "--l-service" },
  repository: { label: "Repositories", hue: "--l-repo" },
  table: { label: "Tables", hue: "--l-table" },
};
const COL_SPACING = 272;

export const NODE_W: Record<LayerKind, number> = {
  endpoint: 188, controller: 188, service: 188, repository: 188, table: 168,
};
export const NODE_H = 48;

const PITCH: Record<LayerKind, number> = {
  endpoint: 80, controller: 100, service: 96, repository: 110, table: 150,
};

// ---- edge path builders (from the design prototype) ----
export function curvePath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(36, Math.abs(x2 - x1) * 0.48);
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

export function anchorsFor(n: DNode, side: "in" | "out"): { x: number; y: number } {
  const w = NODE_W[n.type] ?? 188;
  const cy = n.y + NODE_H / 2;
  return side === "out" ? { x: n.x + w, y: cy } : { x: n.x, y: cy };
}

export const edgeKey = (e: { from: string; to: string }) => `${e.from}>${e.to}`;
export const keySet = (pairs: [string, string][]) => new Set(pairs.map(([a, b]) => `${a}>${b}`));

function layerOf(n: GraphNode): LayerKind {
  switch (n.kind) {
    case "entry_point": return "endpoint";
    case "logic": return n.metadata?.layer === "controller" ? "controller" : "service";
    case "data_access": return "repository";
    case "table": return "table";
    case "gateway": return "controller";
    case "infra_compute": return "service";
    case "queue":
    case "topic": return "repository";
    case "datastore": return "table";
    default: return "service"; // outbound_call / external_api live with services
  }
}

const INFRA_KINDS = new Set(["infra_compute", "queue", "topic", "datastore", "gateway"]);

function mapEdgeKind(e: GraphEdge): EdgeKind {
  if (e.kind === "MAKES_CALL" || e.kind === "CALLS_SERVICE" || e.kind === "SHARED_TABLE") return "cross";
  if (e.kind === "READS") return "reads";
  if (e.kind === "WRITES") return "writes";
  if ((e.confidence ?? 1) < 0.7) return "low";
  return "normal";
}

export function fileStem(path: string): string {
  const base = path.split("/").pop() ?? path;
  return base.replace(/\.[a-z]+$/i, "");
}

export function adaptGraph(graph: Graph, projects: Project[]): DGraph {
  const projName = new Map(projects.map((p) => [p.id, p.name.split("/").pop() ?? p.name]));
  const inCount = new Map<string, number>();
  const outCount = new Map<string, number>();
  const handlesIn = new Map<string, number>();
  const allEdges = [...graph.edges, ...graph.cross_edges.filter((e) => e.status !== "rejected")];
  for (const e of allEdges) {
    outCount.set(e.src, (outCount.get(e.src) ?? 0) + 1);
    inCount.set(e.dst, (inCount.get(e.dst) ?? 0) + 1);
    if (e.kind === "HANDLES") handlesIn.set(e.dst, (handlesIn.get(e.dst) ?? 0) + 1);
  }

  const projCounts = new Map<string, number>();
  for (const n of graph.nodes) projCounts.set(n.project_id, (projCounts.get(n.project_id) ?? 0) + 1);
  const primaryProject = [...projCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const multiProject = projCounts.size > 1;

  const nodes: DNode[] = graph.nodes.map((n) => {
    const type = layerOf(n);
    const cross = n.kind === "outbound_call" || n.kind === "external_api";
    const infra = INFRA_KINDS.has(n.kind) ? (n.metadata?.infra_type ?? n.kind) : undefined;
    const nIn = inCount.get(n.id) ?? 0;
    const nOut = outCount.get(n.id) ?? 0;
    let label = n.name;
    let sub = "";
    let method: string | undefined;
    let path: string | undefined;
    if (type === "endpoint") {
      method = n.metadata?.http_method ?? "GET";
      path = n.metadata?.path ?? n.name;
      sub = n.metadata?.handler ?? "";
    } else if (infra) {
      sub = [n.metadata?.infra_type, n.metadata?.runtime].filter(Boolean).join(" · ") || n.kind;
    } else if (type === "controller") {
      const r = handlesIn.get(n.id) ?? 0;
      sub = `${r} route${r === 1 ? "" : "s"}`;
    } else if (type === "repository") {
      sub = n.metadata?.entity ? `JPA · ${n.metadata.entity}` : "repository";
    } else if (cross) {
      label = n.metadata?.service ?? n.name;
      sub = [n.metadata?.http_method, n.metadata?.url_template].filter(Boolean).join(" ") || n.kind;
    } else if (type === "service") {
      sub = `${nIn} in · ${nOut} out`;
    }
    return {
      id: n.id, type, label, sub, method, path,
      proj: projName.get(n.project_id) ?? n.project_id,
      cross,
      foreign: multiProject && n.project_id !== primaryProject,
      infra,
      cols: type === "table" && !infra ? (n.metadata?.columns ?? []).map((c: any) => c.name) : undefined,
      x: 0, y: 0, raw: n,
    };
  });

  // neighbor map for barycenter ordering
  const neighbors = new Map<string, string[]>();
  for (const e of allEdges) {
    neighbors.set(e.dst, [...(neighbors.get(e.dst) ?? []), e.src]);
    neighbors.set(e.src, [...(neighbors.get(e.src) ?? []), e.dst]);
  }

  const present = LAYER_ORDER.filter((k) => nodes.some((n) => n.type === k));
  const cols: DCol[] = present.map((k, i) => ({
    id: k, label: LAYER_META[k].label, hue: LAYER_META[k].hue, x: 28 + i * COL_SPACING,
  }));

  const order = new Map<string, number>();
  let maxBottom = 0;
  for (const col of cols) {
    const colNodes = nodes.filter((n) => n.type === col.id);
    if (col.id === "endpoint") {
      colNodes.sort((a, b) => (a.path ?? "").localeCompare(b.path ?? "") || (a.method ?? "").localeCompare(b.method ?? ""));
    } else {
      colNodes.sort((a, b) => {
        const score = (n: DNode) => {
          if (n.cross) return -1; // pin cross/outbound nodes to the top, like the design
          const ns = (neighbors.get(n.id) ?? []).map((id) => order.get(id)).filter((v): v is number => v !== undefined);
          return ns.length ? ns.reduce((s, v) => s + v, 0) / ns.length : 999;
        };
        return score(a) - score(b) || a.label.localeCompare(b.label);
      });
    }
    colNodes.forEach((n, i) => {
      order.set(n.id, i);
      n.x = col.x;
      n.y = 70 + i * PITCH[col.id];
      maxBottom = Math.max(maxBottom, n.y + NODE_H);
    });
  }

  const edges: DEdge[] = allEdges
    .filter((e) => e.kind !== "HANDLES" || true)
    .map((e) => ({ from: e.src, to: e.dst, kind: mapEdgeKind(e), raw: e }));

  const lastX = cols.length ? cols[cols.length - 1].x : 28;
  return {
    nodes,
    edges,
    byId: new Map(nodes.map((n) => [n.id, n])),
    cols,
    links: graph.cross_edges,
    stageW: Math.max(1000, lastX + 188 + 36),
    stageH: Math.max(860, maxBottom + 90),
  };
}

/** highlight a node and its direct neighborhood (service-detail style) */
export function neighborhood(g: DGraph, id: string): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set<string>([id]);
  const edges = new Set<string>();
  for (const e of g.edges) {
    if (e.from === id || e.to === id) {
      nodes.add(e.from);
      nodes.add(e.to);
      edges.add(edgeKey(e));
    }
  }
  return { nodes, edges };
}

/** trace paths (from /trace) → highlight sets */
export function pathsHighlight(paths: string[][]): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set<string>();
  const edges = new Set<string>();
  for (const p of paths) {
    p.forEach((id, i) => {
      nodes.add(id);
      if (i > 0) edges.add(`${p[i - 1]}>${id}`);
    });
  }
  return { nodes, edges };
}
