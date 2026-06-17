import { Icon } from "../icons";
import { NODE_W, type DNode } from "../model";

export type NodeState = "sel" | "hl" | "dim" | null;

export function NodeCard({ n, state, onClick, showCols, sub, x, y, showConf }: {
  n: DNode;
  state: NodeState;
  onClick?: (n: DNode) => void;
  showCols?: boolean;
  sub?: string;
  x?: number;
  y?: number;
  showConf?: boolean;
}) {
  const conf = n.raw.confidence ?? 1;
  const diffState = (n.raw.metadata as Record<string, unknown>)?.__diff as string | undefined;
  const diffCls = diffState === "added" ? "diff-add" : diffState === "removed" ? "diff-del"
    : diffState === "changed" ? "diff-chg" : null;
  const cls = ["node", n.type, state, diffCls].filter(Boolean).join(" ");
  const w = NODE_W[n.type] ?? 188;
  return (
    <div
      className={cls}
      style={{ left: x ?? n.x, top: y ?? n.y, width: w }}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(n); } : undefined}
    >
      {diffCls && (
        <span className={"diff-badge " + diffCls.slice(5)}>
          {diffState === "added" ? "+" : diffState === "removed" ? "−" : "~"}
        </span>
      )}
      <span className="layer-tab" />
      {n.type === "endpoint" ? (
        <div className="node-title">
          <span className={"method " + n.method}>{n.method}</span>
          <span className="path">{n.path}</span>
        </div>
      ) : (
        <div className="node-title" style={{ display: "flex", alignItems: "center", gap: 7 }}>
          {n.cross && <Icon.link style={{ width: 12, height: 12, color: "var(--ink-3)", flex: "none" }} />}
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{n.label}</span>
        </div>
      )}
      <div className="node-sub">
        {n.type === "table" && !n.infra && <Icon.db style={{ width: 11, height: 11 }} />}
        {n.infra && <Icon.link style={{ width: 11, height: 11 }} />}
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
          {sub ?? (n.type === "table" && !n.infra ? `${(n.cols ?? []).length} columns` : n.sub)}
        </span>
        {(n.cross || n.foreign || n.infra) && (
          <span className="proj-chip" style={{ color: "var(--l-service)" }}>
            {n.foreign && !n.cross ? n.proj : n.infra ?? n.proj}
          </span>
        )}
        {showConf && conf < 1 && (
          <span className="proj-chip" style={{ marginLeft: "auto", color: "var(--ink-4)" }}>{conf.toFixed(2)}</span>
        )}
      </div>
      {showCols && n.cols && n.cols.length > 0 && (
        <div className="tbl-cols">
          {n.cols.slice(0, 8).map((c) => <span key={c} className="tbl-col">{c}</span>)}
        </div>
      )}
    </div>
  );
}
