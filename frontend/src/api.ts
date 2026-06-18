declare global {
  interface Window {
    __ONBOARDER__?: { apiBase?: string; workspaceId?: string };
    acquireVsCodeApi?: () => { postMessage(msg: unknown): void };
  }
}

const BASE = window.__ONBOARDER__?.apiBase ?? import.meta.env.VITE_API_BASE ?? "/api";

export interface Workspace {
  id: string;
  name: string;
  created_at: string;
  project_count?: number;
  projects?: Project[];
}

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  stack: string;
  status: "pending" | "analyzing" | "ready" | "failed";
  error?: string | null;
  stats: Record<string, number | string>;
  created_at: string;
}

export interface Evidence {
  file: string;
  line: number;
  snippet: string;
}

export interface GraphNode {
  id: string;
  workspace_id: string;
  project_id: string;
  kind: "entry_point" | "logic" | "data_access" | "table" | "outbound_call" | "queue"
    | "external_api" | "infra_compute" | "topic" | "datastore" | "gateway";
  name: string;
  qualified_name?: string;
  file?: string;
  line_start?: number;
  line_end?: number;
  metadata: Record<string, any>;
  confidence: number;
}

export interface GraphEdge {
  id?: number;
  src: string;
  dst: string;
  kind: string;
  confidence: number;
  evidence: Evidence[];
  status?: "inferred" | "confirmed" | "rejected";
  __diff?: "added" | "removed";
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  cross_edges: GraphEdge[];
}

export interface Card {
  purpose: string;
  business_rules: string[];
  side_effects: string[];
  gotchas: string[];
  generated_from?: { file: string | null; start: number; end: number; lines: number };
}

export interface NodeDetail extends GraphNode {
  out_edges: (GraphEdge & { dst_name: string; dst_kind: string })[];
  in_edges: (GraphEdge & { src_name: string; src_kind: string })[];
  card: Card | null;
}

export interface SourceSlice {
  file: string;
  start: number;
  end: number;
  content: string;
}

export interface Settings {
  llm_enabled: boolean;
  key_source: "stored" | "env" | "none";
  model: string;
  stored_key_preview: string | null;
}

export interface TourStep {
  title: string;
  narration: string;
  node_ids: string[];
  mode: "highlight" | "trace" | "isolate";
}

export interface Tour {
  id: number;
  title: string;
  steps: TourStep[];
}

export interface SnapshotMeta {
  id: number;
  label: string;
  kind: "manual" | "auto" | "git";
  git_ref: string | null;
  created_at: string;
  node_count: number;
  edge_count: number;
}

export interface DiffResult {
  base: { id?: number; label: string; kind: string; created_at?: string };
  target: { label: string };
  added_nodes: GraphNode[];
  removed_nodes: GraphNode[];
  changed_nodes: { node: GraphNode; changes: Record<string, [unknown, unknown]> }[];
  added_edges: GraphEdge[];
  removed_edges: GraphEdge[];
  stats: Record<string, { added: number; removed: number; changed: number }>;
  total_changes: number;
}

async function j<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch { /* not json */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  health: async () => j<{ status: string; llm_enabled: boolean; model: string }>(await fetch(`${BASE}/health`)),

  listWorkspaces: async () => j<Workspace[]>(await fetch(`${BASE}/workspaces`)),
  createWorkspace: async (name: string) =>
    j<Workspace>(await fetch(`${BASE}/workspaces`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name }),
    })),
  getWorkspace: async (id: string) => j<Workspace>(await fetch(`${BASE}/workspaces/${id}`)),

  uploadZip: async (wsId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return j<{ projects: Project[] }>(await fetch(`${BASE}/workspaces/${wsId}/projects`, { method: "POST", body: fd }));
  },
  listProjects: async (wsId: string) => j<Project[]>(await fetch(`${BASE}/workspaces/${wsId}/projects`)),
  reanalyze: async (wsId: string, projectId: string) =>
    j<{ id: string; status: string }>(await fetch(`${BASE}/workspaces/${wsId}/projects/${projectId}/reanalyze`, { method: "POST" })),

  getGraph: async (wsId: string, projectId?: string) => {
    const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return j<Graph>(await fetch(`${BASE}/workspaces/${wsId}/graph${q}`));
  },
  getNode: async (wsId: string, nodeId: string) =>
    j<NodeDetail>(await fetch(`${BASE}/workspaces/${wsId}/nodes/${encodeURIComponent(nodeId)}`)),
  enrich: async (wsId: string, nodeId: string) =>
    j<{ node_id: string; card: Card }>(await fetch(`${BASE}/workspaces/${wsId}/nodes/${encodeURIComponent(nodeId)}/enrich`, { method: "POST" })),
  trace: async (wsId: string, fromId: string, toId?: string) => {
    const p = new URLSearchParams({ from_id: fromId });
    if (toId) p.set("to_id", toId);
    return j<{ paths: string[][] }>(await fetch(`${BASE}/workspaces/${wsId}/trace?${p}`));
  },
  getSource: async (wsId: string, projectId: string, file: string, start?: number, end?: number) => {
    const p = new URLSearchParams({ project_id: projectId, file });
    if (start) p.set("start", String(start));
    if (end) p.set("end", String(end));
    return j<SourceSlice>(await fetch(`${BASE}/workspaces/${wsId}/source?${p}`));
  },
  chatHistory: async (wsId: string) =>
    j<{ id: number; role: string; content: string }[]>(await fetch(`${BASE}/workspaces/${wsId}/chat/history`)),
  getSettings: async () => j<Settings>(await fetch(`${BASE}/settings`)),
  setApiKey: async (key: string) =>
    j<Settings>(await fetch(`${BASE}/settings/api-key`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ anthropic_api_key: key }),
    })),
  clearApiKey: async () =>
    j<Settings>(await fetch(`${BASE}/settings/api-key`, { method: "DELETE" })),
  listSnapshots: async (wsId: string) =>
    j<SnapshotMeta[]>(await fetch(`${BASE}/workspaces/${wsId}/snapshots`)),
  createSnapshot: async (wsId: string, body: { label?: string; git_ref?: string }) =>
    j<SnapshotMeta>(await fetch(`${BASE}/workspaces/${wsId}/snapshots`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    })),
  getDiff: async (wsId: string, base: string) =>
    j<DiffResult>(await fetch(`${BASE}/workspaces/${wsId}/diff?base=${encodeURIComponent(base)}`)),
  listTours: async (wsId: string) => j<Tour[]>(await fetch(`${BASE}/workspaces/${wsId}/tours`)),
  generateTour: async (wsId: string) =>
    j<Tour>(await fetch(`${BASE}/workspaces/${wsId}/tours`, { method: "POST" })),
  updateLink: async (wsId: string, linkId: number, status: "confirmed" | "rejected" | "inferred") =>
    j<{ id: number; status: string }>(await fetch(`${BASE}/workspaces/${wsId}/links/${linkId}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    })),
  runLinker: async (wsId: string) =>
    j<{ links: number }>(await fetch(`${BASE}/workspaces/${wsId}/link`, { method: "POST" })),

  trackersStatus: async () => j<TrackerStatus>(await fetch(`${BASE}/trackers/status`)),
  setJira: async (body: { base_url: string; email: string; api_token: string }) =>
    j<TrackerStatus>(await fetch(`${BASE}/trackers/jira`, {
      method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    })),
  setAdo: async (body: { org: string; project: string; pat: string }) =>
    j<TrackerStatus>(await fetch(`${BASE}/trackers/ado`, {
      method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    })),
  clearJira: async () => j<TrackerStatus>(await fetch(`${BASE}/trackers/jira`, { method: "DELETE" })),
  clearAdo: async () => j<TrackerStatus>(await fetch(`${BASE}/trackers/ado`, { method: "DELETE" })),
  getTicket: async (source: string, key: string) =>
    j<Ticket>(await fetch(`${BASE}/trackers/${source}/issue/${encodeURIComponent(key)}`)),
  postTicketComment: async (source: string, key: string, text: string) =>
    j<{ ok: boolean; url: string }>(await fetch(
      `${BASE}/trackers/${source}/issue/${encodeURIComponent(key)}/comment`, {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }),
      })),
};

export function eventsUrl(wsId: string): string {
  return `${BASE}/workspaces/${wsId}/events`;
}

export type ChatEvent =
  | { event: "text_delta"; data: { text: string } }
  | { event: "tool_started"; data: { name: string; input: Record<string, any> } }
  | { event: "ui_directive"; data: { node_ids: string[]; mode: "highlight" | "isolate" | "trace" } }
  | { event: "done"; data: { usage?: Record<string, number> } }
  | { event: "error"; data: { message: string } };

async function* sseFrames(resp: Response): AsyncGenerator<{ event: string; data: any }> {
  if (!resp.ok || !resp.body) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch { /* not json */ }
    yield { event: "error", data: { message: detail } };
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      try {
        yield { event, data: JSON.parse(data) };
      } catch { /* skip malformed frame */ }
    }
  }
}

export async function* chatStream(wsId: string, message: string): AsyncGenerator<ChatEvent> {
  const resp = await fetch(`${BASE}/workspaces/${wsId}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message }),
  });
  for await (const frame of sseFrames(resp)) yield frame as ChatEvent;
}

export interface TrackerStatus {
  jira: { configured: boolean; base_url: string | null; email: string | null };
  ado: { configured: boolean; org: string | null; project: string | null };
}

export interface Ticket {
  source: string;
  key: string;
  title: string;
  body: string;
  type: string | null;
  status: string | null;
  labels: string[];
  comments: string[];
  url: string | null;
}

export interface FixRootCause {
  summary: string;
  file: string;
  line?: number;
  node_id?: string;
}

export interface FixProposal {
  problem: string;
  root_cause: FixRootCause[];
  proposed_fix: string;
  implementation_prompt: string;
  risks: string[];
  confidence: "high" | "medium" | "low";
  focus_node_ids?: string[];
}

export type FixEvent =
  | { event: "ticket"; data: Ticket }
  | { event: "text_delta"; data: { text: string } }
  | { event: "tool_started"; data: { name: string; input: Record<string, any> } }
  | { event: "ui_directive"; data: { node_ids: string[]; mode: "highlight" | "isolate" | "trace" } }
  | { event: "fix_proposal"; data: FixProposal }
  | { event: "done"; data: { usage?: Record<string, number>; had_proposal?: boolean } }
  | { event: "error"; data: { message: string } };

export async function* ticketAnalyzeStream(
  wsId: string, source: string, key: string,
  manual?: { title?: string; body: string },
): AsyncGenerator<FixEvent> {
  const resp = await fetch(
    `${BASE}/workspaces/${wsId}/tickets/${source}/${encodeURIComponent(key)}/analyze`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(manual ?? {}),
    });
  for await (const frame of sseFrames(resp)) yield frame as FixEvent;
}
