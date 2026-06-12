import { useEffect, useState } from "react";
import { api, type Card, type Evidence, type NodeDetail } from "../api";
import { Icon, Spinner } from "../icons";
import { fileStem, type DGraph } from "../model";
import { inVsCode, openInEditor } from "../vscode";
import { CodeViewer } from "./CodeViewer";

export function EvidenceLink({ ev, onOpen }: { ev: Evidence; onOpen?: (ev: Evidence) => void }) {
  const short = `${ev.file.split("/").pop()}:${ev.line}`;
  return (
    <a className="evidence" onClick={(e) => { e.preventDefault(); onOpen?.(ev); }} title={ev.snippet}>
      <Icon.file />{short}
    </a>
  );
}

export function CodePeek({ wsId, projectId, ev }: { wsId: string; projectId: string; ev: Evidence }) {
  const [slice, setSlice] = useState<{ lines: string[]; start: number } | null>(null);
  useEffect(() => {
    let alive = true;
    const start = Math.max(1, ev.line - 6);
    api.getSource(wsId, projectId, ev.file, start, ev.line + 6)
      .then((s) => alive && setSlice({ lines: s.content.split("\n").map((l) => l.replace(/^\d+\t/, "")), start: s.start }))
      .catch(() => alive && setSlice(null));
    return () => { alive = false; };
  }, [wsId, projectId, ev]);
  if (!slice) return null;
  return (
    <div style={{ marginTop: 10 }}>
      <CodeViewer
        title={ev.file.split("/").pop() ?? ev.file}
        meta={`line ${ev.line}`}
        lines={slice.lines}
        startLine={slice.start}
        hlLines={new Set([ev.line])}
      />
    </div>
  );
}

export function LinksSection({ wsId, g, nodeId, onChanged }: {
  wsId: string;
  g: DGraph;
  nodeId: string;
  onChanged: () => void;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const links = g.links.filter((l) => l.id != null && (l.src === nodeId || l.dst === nodeId));
  if (!links.length) return null;

  const setStatus = async (linkId: number, status: "confirmed" | "rejected") => {
    setBusyId(linkId);
    try {
      await api.updateLink(wsId, linkId, status);
      onChanged();
    } finally {
      setBusyId(null);
    }
  };
  const statusColor: Record<string, string> = {
    confirmed: "var(--reads)", rejected: "var(--writes)", inferred: "var(--ink-3)",
  };

  return (
    <div className="panel-section">
      <div className="sec-label">Cross-project links <span className="num">({links.length})</span></div>
      {links.map((l) => {
        const otherId = l.src === nodeId ? l.dst : l.src;
        const other = g.byId.get(otherId);
        const color = statusColor[l.status ?? "inferred"];
        return (
          <div key={l.id} className="rw-row">
            <div className="rw-chain">
              <span className="chain-chip">{other?.label ?? otherId.split(":").pop()}</span>
              <span style={{ fontSize: 10.5, color: "var(--ink-3)" }}>
                {l.kind === "SHARED_TABLE" ? "shared table" : "calls"} · {other?.proj} · conf {l.confidence}
              </span>
              <span className="kind-badge" style={{ color, borderColor: color }}>{l.status}</span>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {l.status !== "confirmed" && (
                <button className="tbtn" style={{ height: 24, fontSize: 11, padding: "0 8px" }}
                  disabled={busyId === l.id} onClick={() => void setStatus(l.id!, "confirmed")}>
                  Confirm
                </button>
              )}
              {l.status !== "rejected" && (
                <button className="tbtn" style={{ height: 24, fontSize: 11, padding: "0 8px" }}
                  disabled={busyId === l.id} onClick={() => void setStatus(l.id!, "rejected")}>
                  Reject
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AIHead({ card }: { card?: Card | null }) {
  const gf = card?.generated_from;
  const meta = gf?.file
    ? `Generated from ${gf.file.split("/").pop()}:${gf.start}–${gf.end} · ${gf.lines} lines only`
    : "Generated from code · evidence-linked";
  return (
    <div className="ai-head">
      <Icon.spark className="ai-spark" />
      <div>
        <div className="ai-label">AI summary</div>
        <div className="ai-meta">{meta}</div>
      </div>
    </div>
  );
}

export function AICard({ wsId, nodeId, card, llmEnabled }: {
  wsId: string;
  nodeId: string;
  card: Card | null;
  llmEnabled: boolean;
}) {
  const [local, setLocal] = useState<Card | null>(card);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setLocal(card); setErr(null); }, [nodeId, card]);

  const generate = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.enrich(wsId, nodeId);
      setLocal(r.card);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ai-card">
      <AIHead card={local} />
      {local ? (
        <>
          <div className="ai-sec"><h5>Purpose</h5><p>{local.purpose}</p></div>
          {local.business_rules.length > 0 && (
            <div className="ai-sec"><h5>Business rules</h5><ul>{local.business_rules.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
          )}
          {local.side_effects.length > 0 && (
            <div className="ai-sec"><h5>Side effects</h5><ul>{local.side_effects.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
          )}
          {local.gotchas.length > 0 && (
            <div className="ai-sec gotcha"><h5>Gotchas</h5><ul>{local.gotchas.map((r, i) => <li key={i}>{r}</li>)}</ul></div>
          )}
        </>
      ) : !llmEnabled ? (
        <div className="ai-note">Add your Anthropic API key in Settings (gear icon) to generate summaries.</div>
      ) : busy ? (
        <div className="ai-gen"><Spinner size={16} />Reading the code…</div>
      ) : (
        <div className="ai-gen" onClick={generate}>
          <Icon.spark style={{ width: 14, height: 14 }} />
          {err ? `Failed (${err}) — retry` : "Generate summary from code"}
        </div>
      )}
    </div>
  );
}

// ---------- table detail ----------
interface RWRow {
  left: string;
  right: string;
  same: boolean;
  ev: Evidence | null;
}

function rwRows(detail: NodeDetail, kind: "WRITES" | "READS"): RWRow[] {
  const rows: RWRow[] = [];
  const seen = new Set<string>();
  for (const e of detail.in_edges.filter((e) => e.kind === kind)) {
    const evs = e.evidence?.length ? e.evidence : [null];
    for (const ev of evs) {
      const left = ev ? fileStem(ev.file) : e.src_name;
      const method = ev?.snippet?.match(/\.?(\w+)\(/)?.[1];
      const right = `${e.src_name}${method ? "." + method : ""}`;
      const key = `${left}|${right}|${ev?.line ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({ left, right, same: left === e.src_name, ev });
    }
  }
  return rows;
}

export function TablePanel({ wsId, g, detail, projName, onClose, onReload }: {
  wsId: string;
  g: DGraph;
  detail: NodeDetail;
  projName: string;
  onClose: () => void;
  onReload: () => void;
}) {
  const [peek, setPeek] = useState<Evidence | null>(null);
  useEffect(() => setPeek(null), [detail.id]);
  const openEv = (ev: Evidence) => {
    if (inVsCode) openInEditor(detail.project_id, ev.file, ev.line);
    else setPeek(ev);
  };
  const writers = rwRows(detail, "WRITES");
  const readers = rwRows(detail, "READS");
  const cols: { name: string; type: string; pk: boolean }[] = detail.metadata?.columns ?? [];
  const sharedWith = g.links
    .filter((l) => l.kind === "SHARED_TABLE" && l.status !== "rejected"
      && (l.src === detail.id || l.dst === detail.id))
    .map((l) => g.byId.get(l.src === detail.id ? l.dst : l.src)?.proj)
    .filter((p): p is string => !!p);
  return (
    <div className="panel" onClick={(e) => e.stopPropagation()}>
      <div className="panel-head">
        <div className="panel-eyebrow">
          <span style={{ width: 8, height: 8, borderRadius: 3, background: "var(--l-table)", display: "inline-block" }} />
          TABLE · {projName}
          <button className="panel-close" onClick={onClose}><Icon.x /></button>
        </div>
        <div className="panel-title"><Icon.db style={{ width: 18, height: 18, color: "var(--l-table)" }} />{detail.name}</div>
        <div style={{ display: "flex", gap: 7, marginTop: 11, flexWrap: "wrap" }}>
          <span className="kind-badge">{cols.length} columns</span>
          <span className="kind-badge" style={{ color: "var(--writes)", borderColor: "var(--writes)" }}>{writers.length} writers</span>
          <span className="kind-badge" style={{ color: "var(--reads)", borderColor: "var(--reads)" }}>{readers.length} readers</span>
          {sharedWith.length > 0 && (
            <span className="kind-badge" style={{ color: "var(--m-put)", borderColor: "var(--m-put)" }}>
              shared with {sharedWith.join(", ")}
            </span>
          )}
        </div>
      </div>
      <div className="panel-body">
        <div className="panel-section">
          <div className="sec-label">
            <span style={{ width: 7, height: 7, borderRadius: 2, background: "var(--writes)" }} />
            Writers <span className="num">({writers.length})</span>
          </div>
          {writers.map((w, i) => (
            <div key={i} className="rw-row writes">
              <div className="rw-chain">
                {!w.same && (
                  <>
                    <span className="chain-chip">{w.left}</span>
                    <Icon.arrow style={{ width: 12, height: 12, color: "var(--ink-4)" }} />
                  </>
                )}
                <span className="chain-chip">{w.right}</span>
              </div>
              {w.ev && <EvidenceLink ev={w.ev} onOpen={openEv} />}
            </div>
          ))}
          {!writers.length && <div className="ai-note">No writers found in the graph.</div>}
        </div>

        <div className="panel-section">
          <div className="sec-label">
            <span style={{ width: 7, height: 7, borderRadius: 2, background: "var(--reads)" }} />
            Readers <span className="num">({readers.length})</span>
          </div>
          {readers.map((r, i) => (
            <div key={i} className="rw-row reads">
              <div className="rw-chain">
                {!r.same && (
                  <>
                    <span className="chain-chip">{r.left}</span>
                    <Icon.arrow style={{ width: 12, height: 12, color: "var(--ink-4)" }} />
                  </>
                )}
                <span className="chain-chip">{r.right}</span>
              </div>
              {r.ev && <EvidenceLink ev={r.ev} onOpen={openEv} />}
            </div>
          ))}
          {!readers.length && <div className="ai-note">No readers found in the graph.</div>}
        </div>

        {cols.length > 0 && (
          <div className="panel-section">
            <div className="sec-label">Columns <span className="num">({cols.length})</span></div>
            <div className="col-list">
              {cols.map((c) => (
                <div key={c.name} className="col-item">
                  <span>{c.name}</span>
                  {c.pk && <span className="pk">PK</span>}
                  <span className="col-type">{c.type}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {peek && <CodePeek wsId={wsId} projectId={detail.project_id} ev={peek} />}

        <LinksSection wsId={wsId} g={g} nodeId={detail.id} onChanged={onReload} />

        <div className="panel-section" style={{ marginTop: 18 }}>
          <div className="sec-label">Legend</div>
          <div className="legend">
            <div className="legend-row"><span className="legend-swatch writes" />red — writes to this table</div>
            <div className="legend-row"><span className="legend-swatch reads" />green — reads from this table</div>
            <div className="legend-row"><span className="legend-swatch cross" />dotted — cross-project / shared</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- logic / repository / outbound detail ----------
export function NodePanel({ wsId, g, detail, llmEnabled, onClose, onJump, onReload }: {
  wsId: string;
  g: DGraph;
  detail: NodeDetail;
  llmEnabled: boolean;
  onClose: () => void;
  onJump: (nodeId: string) => void;
  onReload: () => void;
}) {
  const dn = g.byId.get(detail.id);
  const [code, setCode] = useState<{ lines: string[]; start: number } | null>(null);
  useEffect(() => {
    setCode(null);
    if (!detail.file || !detail.line_start) return;
    let alive = true;
    const start = detail.line_start;
    const end = Math.min(detail.line_end ?? start + 38, start + 38);
    api.getSource(wsId, detail.project_id, detail.file, start, end)
      .then((s) => alive && setCode({ lines: s.content.split("\n").map((l) => l.replace(/^\d+\t/, "")), start: s.start }))
      .catch(() => alive && setCode(null));
    return () => { alive = false; };
  }, [wsId, detail.id]);

  const hueVar: Record<string, string> = {
    controller: "--l-controller", service: "--l-service", repository: "--l-repo",
    endpoint: "--l-endpoint", table: "--l-table",
  };
  const layer = dn?.type ?? "service";
  const evLines = new Set(
    detail.out_edges.flatMap((e) => (e.evidence ?? []).filter((ev) => ev.file === detail.file).map((ev) => ev.line)),
  );
  const kindLabel = detail.kind === "outbound_call" ? "OUTBOUND" : layer.toUpperCase();

  return (
    <div className="panel" style={{ width: 400 }} onClick={(e) => e.stopPropagation()}>
      <div className="panel-head">
        <div className="panel-eyebrow">
          <span style={{ width: 8, height: 8, borderRadius: 3, background: `var(${hueVar[layer]})`, display: "inline-block" }} />
          {kindLabel} · {dn?.proj}
          <button className="panel-close" onClick={onClose}><Icon.x /></button>
        </div>
        <div className="panel-title">{detail.name}</div>
        <div style={{ display: "flex", gap: 7, marginTop: 11 }}>
          {detail.metadata?.language && <span className="kind-badge">{detail.metadata.language}</span>}
          <span className="kind-badge">{detail.in_edges.length} in · {detail.out_edges.length} out</span>
          {detail.confidence < 1 && <span className="kind-badge">conf {detail.confidence.toFixed(2)}</span>}
        </div>
      </div>
      <div className="panel-body">
        {detail.kind !== "outbound_call" && (
          <AICard wsId={wsId} nodeId={detail.id} card={detail.card} llmEnabled={llmEnabled} />
        )}

        {code && detail.file && (
          <>
            <div className="sec-label">Source · {fileStem(detail.file)}</div>
            <CodeViewer
              title={detail.file.split("/").pop() ?? detail.file}
              meta={`lines ${code.start}–${code.start + code.lines.length - 1}`}
              lines={code.lines}
              startLine={code.start}
              hlLines={evLines}
            />
          </>
        )}

        {detail.out_edges.length > 0 && (
          <div className="panel-section" style={{ marginTop: 18 }}>
            <div className="sec-label">Depends on <span className="num">(out)</span></div>
            <div className="dep-list">
              {detail.out_edges.map((e, i) => (
                <div key={i} className="dep-item" style={{ cursor: "pointer" }} onClick={() => onJump(e.dst)}>
                  <Icon.arrow style={{ width: 13, height: 13 }} />
                  {e.dst_name}
                  <span style={{ marginLeft: "auto", color: "var(--ink-4)", fontSize: 10 }}>{e.kind.toLowerCase()}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {detail.in_edges.length > 0 && (
          <div className="panel-section">
            <div className="sec-label">Called by <span className="num">(in)</span></div>
            <div className="dep-list">
              {detail.in_edges.map((e, i) => (
                <div key={i} className="dep-item" style={{ cursor: "pointer" }} onClick={() => onJump(e.src)}>
                  <Icon.arrow style={{ width: 13, height: 13, transform: "rotate(180deg)" }} />
                  {e.src_name}
                  <span style={{ marginLeft: "auto", color: "var(--ink-4)", fontSize: 10 }}>{e.kind.toLowerCase()}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <LinksSection wsId={wsId} g={g} nodeId={detail.id} onChanged={onReload} />

        <div className="panel-section">
          <div className="sec-label">Legend</div>
          <div className="legend">
            <div className="legend-row"><span className="legend-swatch low" />dashed — low-confidence link</div>
            <div className="legend-row"><span className="legend-swatch cross" />dotted — cross-project / outbound call</div>
          </div>
        </div>
      </div>
    </div>
  );
}
