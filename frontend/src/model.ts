import type { Graph, GraphEdge, GraphNode, Project } from "./api";

export type LayerKind = "endpoint" | "controller" | "service" | "repository" | "graphql" | "table" | "messaging";
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
  group: string;        // package/folder cluster id (within its column)
  order: number;        // stable index within its column (barycenter order)
  x: number;
  y: number;
  raw: GraphNode;
}

// A package/folder cluster inside one layer column. Dense columns collapse their
// members into these cards so a repo with hundreds of classes stays navigable.
export interface DGroup {
  id: string;
  col: LayerKind;
  label: string;        // last package segment, e.g. "billing"
  title: string;        // full package path, e.g. "com.acme.billing"
  memberIds: string[];  // ordered
  collapsible: boolean; // its column is dense enough to group
  // filled by relayout:
  x: number;
  y: number;
  w: number;
  h: number;
  collapsed: boolean;
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
  groups: DGroup[];
  links: GraphEdge[];
  stageW: number;
  stageH: number;
}

const LAYER_ORDER: LayerKind[] = ["endpoint", "controller", "service", "repository", "graphql", "table", "messaging"];
const LAYER_META: Record<LayerKind, { label: string; hue: string }> = {
  endpoint: { label: "Endpoints", hue: "--l-endpoint" },
  controller: { label: "Controllers", hue: "--l-controller" },
  service: { label: "Services", hue: "--l-service" },
  repository: { label: "Repositories", hue: "--l-repo" },
  graphql: { label: "GraphQL types", hue: "--l-graphql" },
  table: { label: "Tables", hue: "--l-table" },
  messaging: { label: "Messaging", hue: "--l-messaging" },
};
const COL_SPACING = 272;

export const NODE_W: Record<LayerKind, number> = {
  endpoint: 188, controller: 188, service: 188, repository: 188, graphql: 180, table: 168, messaging: 180,
};
export const NODE_H = 48;

const PITCH: Record<LayerKind, number> = {
  endpoint: 80, controller: 100, service: 96, repository: 110, graphql: 96, table: 150, messaging: 110,
};

// Package grouping: a column with more than DENSE_MIN nodes spread over at least
// GROUP_MIN packages collapses into package cards instead of a scroll-wall.
const DENSE_MIN = 16;
const GROUP_MIN = 3;
export const GROUP_W = 212;
const GROUP_COLLAPSED_H = 58;
const GROUP_HEAD_H = 34;
const GROUP_GAP = 16;
const GROUP_PAD = 11;
const NODE_GAP = 8;
const COL_TOP = 70;

const SRC_ROOT = /^(?:app\/)?src\/(?:main\/)?(?:java|kotlin|scala|groovy|resources)\/|^(?:app\/)?src\/|^app\//;

/** Package / folder of a source file, used to cluster a column's nodes. */
export function packageKey(file?: string): { id: string; label: string; title: string } {
  if (!file) return { id: "~root", label: "root", title: "(top level)" };
  const parts = file.split("/");
  parts.pop(); // drop filename
  let dir = parts.join("/").replace(SRC_ROOT, "");
  if (!dir) return { id: "~root", label: "root", title: "top level" };
  const segs = dir.split("/").filter(Boolean);
  const label = segs[segs.length - 1] || "root";
  // dotted for java-ish deep packages, slashes for shallow web folders
  const title = segs.length > 2 ? segs.join(".") : segs.join("/");
  return { id: dir, label, title };
}

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
    case "page":
    case "screen": return "endpoint";
    case "logic": return n.metadata?.layer === "controller" ? "controller" : "service";
    case "data_access": return "repository";
    case "graphql_entity": return "graphql";
    case "table": return "table";
    case "gateway": return "controller";
    case "infra_compute": return "service";
    case "queue":
    case "topic": return "messaging";
    case "datastore": return "table";
    default: return "service"; // outbound_call / external_api live with services
  }
}

const INFRA_KINDS = new Set(["infra_compute", "queue", "topic", "datastore", "gateway"]);

function mapEdgeKind(e: GraphEdge): EdgeKind {
  if (e.kind === "MAKES_CALL" || e.kind === "CALLS_SERVICE" || e.kind === "SHARED_TABLE"
      || e.kind === "GRAPHQL_ENTITY") return "cross";
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
      sub = [n.metadata?.infra_type, n.metadata?.runtime].filter(Boolean).join(" · ")
        || n.metadata?.messaging || n.kind;
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
      group: "", order: 0, x: 0, y: 0, raw: n,
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

  // group each node by package, and order nodes within each column (barycenter, like the design)
  const order = new Map<string, number>();
  const groups: DGroup[] = [];
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
    // assign package groups for this column
    const byPkg = new Map<string, DGroup>();
    colNodes.forEach((n, i) => {
      order.set(n.id, i);
      n.order = i;
      const pk = packageKey(n.raw?.file);
      const gid = `${col.id}::${pk.id}`;
      n.group = gid;
      let gr = byPkg.get(gid);
      if (!gr) {
        gr = { id: gid, col: col.id, label: pk.label, title: pk.title, memberIds: [],
          collapsible: false, x: 0, y: 0, w: GROUP_W, h: GROUP_COLLAPSED_H, collapsed: false };
        byPkg.set(gid, gr);
        groups.push(gr);
      }
      gr.memberIds.push(n.id);
    });
    const colGroups = [...byPkg.values()];
    // a column groups only when it is both crowded and genuinely multi-package
    const dense = colNodes.length > DENSE_MIN && colGroups.length >= GROUP_MIN;
    for (const gr of colGroups) gr.collapsible = dense;
  }

  const edges: DEdge[] = allEdges
    .filter((e) => e.kind !== "HANDLES" || true)
    .map((e) => ({ from: e.src, to: e.dst, kind: mapEdgeKind(e), raw: e }));

  const g: DGraph = {
    nodes,
    edges,
    byId: new Map(nodes.map((n) => [n.id, n])),
    cols,
    groups,
    links: graph.cross_edges,
    stageW: 1000,
    stageH: 860,
  };
  // default layout: dense columns start collapsed
  const def = relayout(g, new Set(groups.filter((gr) => gr.collapsible).map((gr) => gr.id)));
  for (const n of nodes) { const p = def.pos.get(n.id); if (p) { n.x = p.x; n.y = p.y; } }
  g.stageW = def.stageW;
  g.stageH = def.stageH;
  return g;
}

export interface LayoutResult {
  pos: Map<string, { x: number; y: number }>;
  groups: DGroup[];           // placed (collapsed ones carry boxes; all carry x/y/h/collapsed)
  stageW: number;
  stageH: number;
}

/** Position a column either as individual node cards (sparse columns, or expanded
 *  packages) or as collapsed package cards, given which group ids are collapsed. */
export function relayout(g: DGraph, collapsed: Set<string>): LayoutResult {
  const pos = new Map<string, { x: number; y: number }>();
  const placed: DGroup[] = [];
  const nodeById = g.byId;
  let maxBottom = 0;
  let lastX = 28;
  for (const col of g.cols) {
    const x = col.x;
    lastX = x;
    const colGroups = g.groups.filter((gr) => gr.col === col.id)
      .sort((a, b) => (nodeById.get(a.memberIds[0])?.order ?? 0) - (nodeById.get(b.memberIds[0])?.order ?? 0));
    const grouped = colGroups.some((gr) => gr.collapsible);
    let y = COL_TOP;
    if (!grouped) {
      // sparse column: plain vertical stack of nodes, original behavior
      const colNodes = g.nodes.filter((n) => n.type === col.id).sort((a, b) => a.order - b.order);
      for (const n of colNodes) {
        pos.set(n.id, { x, y });
        y += PITCH[col.id];
      }
      maxBottom = Math.max(maxBottom, y);
      continue;
    }
    for (const gr of colGroups) {
      if (collapsed.has(gr.id)) {
        placed.push({ ...gr, x, y, w: GROUP_W, h: GROUP_COLLAPSED_H, collapsed: true });
        y += GROUP_COLLAPSED_H + GROUP_GAP;
      } else {
        const members = [...gr.memberIds].sort((a, b) => (nodeById.get(a)?.order ?? 0) - (nodeById.get(b)?.order ?? 0));
        const h = GROUP_HEAD_H + GROUP_PAD + members.length * (NODE_H + NODE_GAP) - NODE_GAP + GROUP_PAD;
        placed.push({ ...gr, x, y, w: GROUP_W, h, collapsed: false });
        let my = y + GROUP_HEAD_H + GROUP_PAD;
        for (const id of members) {
          pos.set(id, { x: x + GROUP_PAD, y: my });
          my += NODE_H + NODE_GAP;
        }
        y += h + GROUP_GAP;
      }
      maxBottom = Math.max(maxBottom, y);
    }
  }
  return {
    pos,
    groups: placed,
    stageW: Math.max(1000, lastX + GROUP_W + 40),
    stageH: Math.max(680, maxBottom + 80),
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
