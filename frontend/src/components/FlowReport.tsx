import type { FlowReport } from "../api";
import { Icon } from "../icons";
import type { DGraph, LayerKind } from "../model";
import { saveArtifact } from "../vscode";

const LAYER_HUE: Record<string, string> = {
  endpoint: "--l-endpoint", controller: "--l-controller", service: "--l-service",
  repository: "--l-repo", graphql: "--l-graphql", table: "--l-table", messaging: "--l-messaging",
};

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s: string): string {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/_([^_]+)_/g, "<em>$1</em>");
}
function mdToHtml(md: string): string {
  const out: string[] = [];
  let inList = false;
  const closeList = () => { if (inList) { out.push("</ol>"); inList = false; } };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    if (/^#\s/.test(line)) { closeList(); out.push(`<h1>${inline(line.slice(2))}</h1>`); continue; }
    if (/^##\s/.test(line)) { closeList(); out.push(`<h2>${inline(line.slice(3))}</h2>`); continue; }
    if (/^-{3,}$/.test(line)) { closeList(); out.push("<hr/>"); continue; }
    const li = line.match(/^\d+\.\s+(.*)/);
    if (li) { if (!inList) { out.push("<ol>"); inList = true; } out.push(`<li>${inline(li[1])}</li>`); continue; }
    closeList();
    if (line === "") continue;
    out.push(`<p>${inline(line)}</p>`);
  }
  closeList();
  return out.join("\n");
}

export function FlowReportModal({ report, g, onClose }: {
  report: FlowReport; g: DGraph; onClose: () => void;
}) {
  const base = report.title.replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "") || "flow";
  const steps = report.node_ids.map((id) => g.byId.get(id)).filter(Boolean);
  return (
    <div className="screen-scrim" onClick={onClose}>
      <div className="flow-modal" onClick={(e) => e.stopPropagation()}>
        <div className="flow-modal-head">
          <div className="flow-modal-title">
            <Icon.spark style={{ width: 15, height: 15, color: "var(--brand)" }} />
            Flow report{report.has_ai ? "" : " · structural"}
          </div>
          <div className="flow-modal-actions">
            <button className="tbtn" onClick={() => saveArtifact(`${base}.md`, report.markdown, "text")}>
              <Icon.download />Markdown
            </button>
            <button className="tbtn" onClick={() => window.print()}><Icon.file />Save as PDF</button>
            <button className="panel-close" onClick={onClose}><Icon.x /></button>
          </div>
        </div>
        <div className="flow-modal-body" id="flow-report-print">
          {steps.length > 1 && (
            <div className="flow-diagram">
              {steps.map((n, i) => (
                <div key={n!.id} className="flow-step-wrap">
                  {i > 0 && <div className="flow-arrow">↓</div>}
                  <div className="flow-step" style={{ borderLeftColor: `var(${LAYER_HUE[n!.type as LayerKind] ?? "--l-service"})` }}>
                    <span className="flow-step-kind">{n!.cross ? "calls" : n!.type}</span>
                    <span className="flow-step-name">{n!.method ? `${n!.method} ${n!.path ?? n!.label}` : n!.label}</span>
                    {n!.proj && <span className="flow-step-proj">{n!.proj}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="flow-md" dangerouslySetInnerHTML={{ __html: mdToHtml(report.markdown) }} />
        </div>
      </div>
    </div>
  );
}
