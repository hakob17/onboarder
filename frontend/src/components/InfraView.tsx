import { useMemo, useState } from "react";
import { Icon } from "../icons";
import { anchorsFor, curvePath, type DGraph, type DNode } from "../model";
import { inVsCode, openInEditor } from "../vscode";
import { CodePeek, EvidenceLink } from "./panels";
import { NodeCard } from "./NodeCard";

const INFRA_KINDS = new Set(["infra_compute", "topic", "datastore", "gateway", "queue"]);
const ROLE_X: Record<string, number> = {
  gateway: 40, entry_point: 40,
  infra_compute: 380,
  datastore: 720, queue: 720, topic: 720,
};
const COL_LABEL: [number, string][] = [[40, "Triggers"], [380, "Compute"], [720, "Data & messaging"]];

interface Placed extends DNode {
  hx: number;
  hy: number;
}

export function InfraView({ wsId, g }: {
  wsId: string;
  g: DGraph;
  onClose: () => void;
}) {
  const [selId, setSelId] = useState<string | null>(null);

  const { placed, byId, edges, stageH } = useMemo(() => {
    const infra = g.nodes.filter((n) => INFRA_KINDS.has(n.raw.kind));
    const computeIds = new Set(infra.filter((n) => n.raw.kind === "infra_compute").map((n) => n.id));
    // entry points / gateways that hand off to a compute node
    const triggers = g.nodes.filter((n) =>
      n.raw.kind === "entry_point" &&
      g.edges.some((e) => e.from === n.id && computeIds.has(e.to)));
    const relevant = [...infra, ...triggers];
    const ids = new Set(relevant.map((n) => n.id));

    const rows: Record<number, number> = {};
    const placed: Placed[] = relevant.map((n) => {
      const kind = n.raw.kind === "entry_point" ? "entry_point" : n.raw.kind;
      const x = ROLE_X[kind] ?? 380;
      const row = rows[x] ?? 0;
      rows[x] = row + 1;
      return { ...n, hx: x, hy: 70 + row * 124 };
    });
    const byId = new Map(placed.map((p) => [p.id, p]));
    const edges = g.edges.filter((e) => ids.has(e.from) && ids.has(e.to));
    const stageH = Math.max(560, ...Object.values(rows).map((r) => 70 + r * 124 + 60));
    return { placed, byId, edges, stageH };
  }, [g]);

  const sel = selId ? byId.get(selId) : null;

  function activate(n: DNode) {
    const md = n.raw.metadata as Record<string, any>;
    if (n.raw.kind === "infra_compute" && md.handler_file && inVsCode) {
      openInEditor(n.raw.project_id, md.handler_file, md.handler_line ?? 1);
    }
    setSelId(n.id);
  }

  if (placed.length === 0) {
    return (
      <div className="body" style={{ display: "grid", placeItems: "center" }}>
        <div className="diff-empty" style={{ maxWidth: 360 }}>
          <Icon.cloud style={{ width: 26, height: 26, color: "var(--ink-3)" }} />
          No infrastructure detected. Add a Terraform (<span className="mono">*.tf</span>) or
          SAM/CloudFormation (<span className="mono">template.yaml</span>) project to see AWS
          services here.
        </div>
      </div>
    );
  }

  return (
    <div className="body" onClick={() => setSelId(null)}>
      <div className="canvas-grid" />
      <div className="map-scroll">
        <div className="map-stage" style={{ width: 940, height: stageH }}>
          <svg className="edges" width={940} height={stageH} viewBox={`0 0 940 ${stageH}`}>
            {edges.map((e, i) => {
              const a = byId.get(e.from);
              const b = byId.get(e.to);
              if (!a || !b) return null;
              const p1 = anchorsFor({ ...a, x: a.hx, y: a.hy } as DNode, "out");
              const p2 = anchorsFor({ ...b, x: b.hx, y: b.hy } as DNode, "in");
              const hl = selId && (e.from === selId || e.to === selId);
              return (
                <path key={i} className={hl ? "edge-hl" : "edge-base"}
                  d={curvePath(p1.x, p1.y, p2.x, p2.y)}
                  style={hl ? undefined : { opacity: 0.5 }} />
              );
            })}
          </svg>
          {COL_LABEL.map(([x, label]) => (
            <div key={x} className="col-head" style={{ position: "absolute", left: x + 2, top: 14 }}>
              {label}
            </div>
          ))}
          {placed.map((n) => (
            <NodeCard key={n.id} n={n} x={n.hx} y={n.hy}
              state={selId === n.id ? "sel" : null}
              onClick={() => activate(n)} />
          ))}
        </div>
      </div>
      {sel && <InfraPanel wsId={wsId} node={sel} onClose={() => setSelId(null)} />}
    </div>
  );
}

function InfraPanel({ wsId, node, onClose }: { wsId: string; node: DNode; onClose: () => void }) {
  const md = node.raw.metadata as Record<string, any>;
  const isCompute = node.raw.kind === "infra_compute";
  const hue = node.raw.kind === "datastore" ? "--l-table"
    : node.raw.kind === "gateway" ? "--l-controller" : "--l-service";
  return (
    <div className="panel" onClick={(e) => e.stopPropagation()}>
      <div className="panel-head">
        <div className="panel-eyebrow">
          <span style={{ width: 8, height: 8, borderRadius: 3, background: `var(${hue})`, display: "inline-block" }} />
          {(md.infra_type ?? node.raw.kind).toUpperCase()} · {(md.source ?? "iac").toUpperCase()}
          <button className="panel-close" onClick={onClose}><Icon.x /></button>
        </div>
        <div className="panel-title">
          {isCompute ? <Icon.bolt style={{ width: 16, height: 16, color: "var(--l-service)" }} /> : null}
          {node.label}
        </div>
        <div style={{ display: "flex", gap: 7, marginTop: 11, flexWrap: "wrap" }}>
          {md.runtime && <span className="kind-badge">{md.runtime}</span>}
          {md.infra_type && <span className="kind-badge">{md.infra_type}</span>}
        </div>
      </div>
      <div className="panel-body">
        <div className="panel-section">
          <div className="sec-label">Declared in</div>
          {node.raw.file && (
            <EvidenceLink ev={{ file: node.raw.file, line: node.raw.line_start ?? 1, snippet: "" }} />
          )}
        </div>

        {isCompute && md.handler_file && (
          <div className="panel-section">
            <div className="sec-label">Handler</div>
            <div className="dep-item" style={{ cursor: inVsCode ? "pointer" : "default", marginBottom: 8 }}
              onClick={() => inVsCode && openInEditor(node.raw.project_id, md.handler_file, md.handler_line ?? 1)}>
              <Icon.arrow style={{ width: 13, height: 13 }} />
              {md.handler_file.split("/").pop()}:{md.handler_line ?? 1}
              {inVsCode && <span style={{ marginLeft: "auto", color: "var(--ink-4)", fontSize: 10 }}>open ↗</span>}
            </div>
            <CodePeek wsId={wsId} projectId={node.raw.project_id}
              ev={{ file: md.handler_file, line: md.handler_line ?? 1, snippet: "" }} />
          </div>
        )}

        {md.env && Object.keys(md.env).length > 0 && (
          <div className="panel-section">
            <div className="sec-label">Environment</div>
            <div className="col-list">
              {Object.entries(md.env).map(([k, v]) => (
                <div key={k} className="col-item">
                  <span>{k}</span>
                  <span className="col-type" style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {String(v)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
