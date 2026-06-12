import type { DiffResult, GraphEdge, GraphNode, SnapshotMeta } from "../api";
import { Icon, Spinner } from "../icons";
import type { DGraph } from "../model";

function timeago(iso?: string): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

const KIND_HUE: Record<string, string> = {
  entry_point: "--l-endpoint", logic: "--l-service", data_access: "--l-repo",
  table: "--l-table", outbound_call: "--l-service",
};

function NodeRow({ n, tone, extra, onFocus }: {
  n: GraphNode;
  tone: "add" | "del" | "chg";
  extra?: string;
  onFocus: (id: string) => void;
}) {
  const toneColor = tone === "add" ? "var(--reads)" : tone === "del" ? "var(--writes)" : "var(--m-put)";
  return (
    <div className="rw-row" style={{ cursor: "pointer" }} onClick={() => onFocus(n.id)}>
      <div className="rw-chain">
        <span className="marker" style={{ width: 7, height: 7, borderRadius: 2, background: toneColor }} />
        <span style={{ width: 7, height: 7, borderRadius: 2, background: `var(${KIND_HUE[n.kind] ?? "--l-service"})` }} />
        <span className="chain-chip">{n.name}</span>
        <span style={{ fontSize: 10.5, color: "var(--ink-3)" }}>{n.kind.replace("_", " ")}</span>
      </div>
      {extra && <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink-3)" }}>{extra}</span>}
    </div>
  );
}

function EdgeRow({ e, tone, g }: { e: GraphEdge; tone: "add" | "del"; g: DGraph }) {
  const name = (id: string) => g.byId.get(id)?.label ?? id.split(":").pop();
  return (
    <div className="diff-edge-row">
      <span className="marker" style={{ background: tone === "add" ? "var(--reads)" : "var(--writes)" }} />
      {name(e.src)} → {name(e.dst)}
      <span style={{ color: "var(--ink-4)" }}>· {e.kind.toLowerCase()}</span>
    </div>
  );
}

export function DiffPanel({ g, diff, snapshots, base, busy, onBase, onSaveBaseline, onClose, onFocus }: {
  g: DGraph;
  diff: DiffResult | null;
  snapshots: SnapshotMeta[];
  base: string;
  busy: boolean;
  onBase: (spec: string) => void;
  onSaveBaseline: () => void;
  onClose: () => void;
  onFocus: (id: string) => void;
}) {
  return (
    <div className="panel" onClick={(e) => e.stopPropagation()}>
      <div className="panel-head">
        <div className="panel-eyebrow">
          <Icon.diff style={{ width: 13, height: 13 }} />
          COMPARE
          <button className="panel-close" onClick={onClose}><Icon.x /></button>
        </div>
        <div style={{ display: "flex", gap: 7, marginTop: 10, alignItems: "center" }}>
          <select
            value={base}
            onChange={(e) => onBase(e.target.value)}
            style={{
              flex: 1, height: 30, border: "1px solid var(--line)", borderRadius: 8,
              background: "var(--surface-2)", color: "var(--ink)", fontFamily: "var(--ui)",
              fontSize: 12, padding: "0 8px",
            }}
          >
            <option value="latest">vs latest snapshot</option>
            {snapshots.map((s) => (
              <option key={s.id} value={String(s.id)}>
                vs {s.label}{s.kind === "git" ? ` (${s.git_ref})` : ""} · {timeago(s.created_at)}
              </option>
            ))}
          </select>
          <button className="tbtn" style={{ height: 30 }} onClick={onSaveBaseline} disabled={busy}>
            Save baseline
          </button>
        </div>
        {diff && (
          <div style={{ display: "flex", gap: 7, marginTop: 10, flexWrap: "wrap" }}>
            <span className="kind-badge" style={{ color: "var(--reads)", borderColor: "var(--reads)" }}>
              +{diff.added_nodes.length} nodes · +{diff.added_edges.length} edges
            </span>
            <span className="kind-badge" style={{ color: "var(--writes)", borderColor: "var(--writes)" }}>
              −{diff.removed_nodes.length} nodes · −{diff.removed_edges.length} edges
            </span>
            <span className="kind-badge" style={{ color: "var(--m-put)", borderColor: "var(--m-put)" }}>
              ~{diff.changed_nodes.length} changed
            </span>
          </div>
        )}
      </div>
      <div className="panel-body">
        {busy && <div className="diff-empty"><Spinner size={20} />comparing…</div>}
        {!busy && diff && diff.total_changes === 0 && (
          <div className="diff-empty">
            <Icon.check style={{ width: 22, height: 22, color: "var(--reads)" }} />
            No changes vs {diff.base.label}.
            <span style={{ color: "var(--ink-4)", fontSize: 11.5 }}>
              Edit code, re-analyze, and come back to verify the flow matches what you expected.
            </span>
          </div>
        )}
        {!busy && diff && diff.total_changes > 0 && (
          <>
            {diff.added_nodes.length > 0 && (
              <div className="panel-section">
                <div className="sec-label">Added <span className="num">({diff.added_nodes.length})</span></div>
                {diff.added_nodes.map((n) => <NodeRow key={n.id} n={n} tone="add" onFocus={onFocus} />)}
              </div>
            )}
            {diff.removed_nodes.length > 0 && (
              <div className="panel-section">
                <div className="sec-label">Removed <span className="num">({diff.removed_nodes.length})</span></div>
                {diff.removed_nodes.map((n) => <NodeRow key={n.id} n={n} tone="del" onFocus={onFocus} />)}
              </div>
            )}
            {diff.changed_nodes.length > 0 && (
              <div className="panel-section">
                <div className="sec-label">Changed <span className="num">({diff.changed_nodes.length})</span></div>
                {diff.changed_nodes.map((c) => (
                  <NodeRow key={c.node.id} n={c.node} tone="chg"
                    extra={Object.keys(c.changes).join(", ")} onFocus={onFocus} />
                ))}
              </div>
            )}
            {diff.added_edges.length > 0 && (
              <div className="panel-section">
                <div className="sec-label">New connections <span className="num">({diff.added_edges.length})</span></div>
                {diff.added_edges.map((e, i) => <EdgeRow key={i} e={e} tone="add" g={g} />)}
              </div>
            )}
            {diff.removed_edges.length > 0 && (
              <div className="panel-section">
                <div className="sec-label">Removed connections <span className="num">({diff.removed_edges.length})</span></div>
                {diff.removed_edges.map((e, i) => <EdgeRow key={i} e={e} tone="del" g={g} />)}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
