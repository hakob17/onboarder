import { useEffect, useRef, useState } from "react";
import {
  api, ticketAnalyzeStream,
  type Evidence, type FixProposal, type Ticket, type TrackerStatus,
} from "../api";
import { Icon } from "../icons";
import type { DGraph } from "../model";
import { inVsCode, openInEditor } from "../vscode";
import { CodePeek, EvidenceLink } from "./panels";

type Source = "manual" | "jira" | "ado";

function activity(name: string, input: Record<string, any>): string {
  switch (name) {
    case "query_graph": return "Queried graph";
    case "trace_paths": return "Traced paths";
    case "read_source": return `Read ${String(input?.file ?? "source").split("/").pop()}`;
    case "search_code": return "Searched code";
    case "get_node": return `Read ${String(input?.node_id ?? "node").split(":").pop()}`;
    case "list_projects": return "Listed projects";
    case "focus_view": return "Highlighted on the map";
    default: return name;
  }
}

function commentText(p: FixProposal): string {
  const causes = p.root_cause.map((c) => `• ${c.file}${c.line ? `:${c.line}` : ""} — ${c.summary}`).join("\n");
  return [
    "Onboarder analysis (static code analysis):",
    "",
    `Problem: ${p.problem}`,
    "",
    `Likely root cause:\n${causes}`,
    "",
    `Proposed fix: ${p.proposed_fix}`,
    "",
    `Confidence: ${p.confidence}.`,
  ].join("\n");
}

export interface TicketRequest {
  source: string;
  key?: string;
  title?: string;
  body?: string;
}

export function TicketsPanel({ wsId, g, llmEnabled, trackers, req, onReqConsumed, onDirective, onChip, onClose }: {
  wsId: string;
  g: DGraph;
  llmEnabled: boolean;
  trackers: TrackerStatus | null;
  req?: TicketRequest | null;
  onReqConsumed?: () => void;
  onDirective: (d: { node_ids: string[]; mode: string }) => void;
  onChip: (id: string) => void;
  onClose: () => void;
}) {
  const haveJira = !!trackers?.jira.configured;
  const haveAdo = !!trackers?.ado.configured;
  const [source, setSource] = useState<Source>(haveJira ? "jira" : haveAdo ? "ado" : "manual");
  const [key, setKey] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");

  const [busy, setBusy] = useState(false);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [acts, setActs] = useState<string[]>([]);
  const [proposal, setProposal] = useState<FixProposal | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [peek, setPeek] = useState<{ ev: Evidence; projectId: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [posting, setPosting] = useState(false);
  const [posted, setPosted] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [acts, proposal, ticket]);

  // analyze request handed in from outside (VS Code "Analyze a ticket" command)
  useEffect(() => {
    if (req && llmEnabled && !busy) {
      const s = (["jira", "ado", "manual"].includes(req.source) ? req.source : "manual") as Source;
      setSource(s);
      if (s === "manual") { setTitle(req.title ?? ""); setBody(req.body ?? ""); }
      else setKey(req.key ?? "");
      onReqConsumed?.();
      void runAnalyze(s, req.key ?? "", req.title ?? "", req.body ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req, llmEnabled]);

  function projectFor(nodeId?: string): string {
    if (nodeId) {
      const n = g.byId.get(nodeId);
      if (n) return n.raw.project_id;
      const pre = nodeId.split(":")[0];
      if (pre) return pre;
    }
    return g.nodes[0]?.raw.project_id ?? "";
  }

  function openCause(file: string, line: number, nodeId?: string) {
    const projectId = projectFor(nodeId);
    if (inVsCode) openInEditor(projectId, file, line);
    else setPeek({ ev: { file, line, snippet: "" }, projectId });
  }

  const analyze = () => runAnalyze(source, key, title, body);

  async function runAnalyze(src: Source, k: string, mTitle: string, mBody: string) {
    if (busy || !llmEnabled) return;
    const manual = src === "manual";
    if (manual && !mBody.trim()) { setErr("Paste the ticket text first."); return; }
    if (!manual && !k.trim()) { setErr("Enter a ticket key."); return; }
    setBusy(true);
    setErr(null);
    setTicket(null);
    setActs([]);
    setProposal(null);
    setPeek(null);
    setPosted(null);
    const idKey = manual ? "ticket" : k.trim();
    try {
      const stream = ticketAnalyzeStream(
        wsId, src, idKey,
        manual ? { title: mTitle.trim() || undefined, body: mBody.trim() } : undefined,
      );
      for await (const ev of stream) {
        if (ev.event === "ticket") setTicket(ev.data);
        else if (ev.event === "tool_started") {
          const label = activity(ev.data.name, ev.data.input);
          setActs((a) => (a.includes(label) ? a : [...a, label]));
        } else if (ev.event === "ui_directive") onDirective(ev.data);
        else if (ev.event === "fix_proposal") setProposal(ev.data);
        else if (ev.event === "error") setErr(ev.data.message);
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function copyPrompt() {
    if (!proposal) return;
    try {
      await navigator.clipboard.writeText(proposal.implementation_prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch { /* clipboard blocked */ }
  }

  async function postComment() {
    if (!proposal || !ticket || source === "manual") return;
    if (!window.confirm(`Post this analysis as a comment on ${source.toUpperCase()} ${ticket.key}?`)) return;
    setPosting(true);
    try {
      const r = await api.postTicketComment(source, ticket.key, commentText(proposal));
      setPosted(r.url);
    } catch (e) {
      setErr(String(e));
    } finally {
      setPosting(false);
    }
  }

  const sources: [Source, string, boolean][] = [
    ["jira", "Jira", haveJira],
    ["ado", "Azure DevOps", haveAdo],
    ["manual", "Paste text", true],
  ];

  return (
    <div className="chat-dock" onClick={(e) => e.stopPropagation()}>
      <div className="chat-head">
        <Icon.spark className="ai-spark" style={{ color: "var(--brand)" }} />
        <div style={{ flex: 1 }}>
          <div className="ttl">Fix from a ticket</div>
          <div className="sub">Jira / ADO → root cause + fix prompt</div>
        </div>
        <button className="tbtn icon" onClick={onClose}><Icon.x /></button>
      </div>

      <div className="chat-body" ref={bodyRef}>
        {!llmEnabled && (
          <div className="msg bot"><div className="bubble">
            Ticket analysis needs an Anthropic API key — add yours in Settings (gear icon, left rail).
          </div></div>
        )}

        {/* ticket input */}
        <div className="panel-section" style={{ marginTop: 0 }}>
          <div className="suggest-row" style={{ marginBottom: 10 }}>
            {sources.map(([s, label, enabled]) => (
              <span key={s}
                className={"suggest" + (source === s ? " on" : "")}
                style={{ opacity: enabled ? 1 : 0.4, pointerEvents: enabled ? "auto" : "none" }}
                onClick={() => enabled && setSource(s)}>
                {label}
              </span>
            ))}
          </div>
          {(!haveJira && !haveAdo) && (
            <div className="sub" style={{ marginBottom: 8 }}>
              Connect Jira or Azure DevOps in Settings to analyze by key — or paste a ticket below.
            </div>
          )}
          {source === "manual" ? (
            <>
              <input className="ti" placeholder="Title (optional)" value={title}
                onChange={(e) => setTitle(e.target.value)} />
              <textarea className="ti" placeholder="Paste the ticket description / repro steps…"
                value={body} rows={5} onChange={(e) => setBody(e.target.value)}
                style={{ resize: "vertical", marginTop: 8 }} />
            </>
          ) : (
            <input className="ti" placeholder={source === "jira" ? "Issue key, e.g. PROJ-123" : "Work item id, e.g. 1234"}
              value={key} onChange={(e) => setKey(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && analyze()} />
          )}
          <button className="btn-primary" style={{ marginTop: 10, width: "100%" }}
            onClick={analyze} disabled={busy || !llmEnabled}>
            {busy ? "Analyzing…" : "Analyze & suggest fix"}
          </button>
        </div>

        {err && <div className="msg bot"><div className="bubble">⚠ {err}</div></div>}

        {ticket && (
          <div className="panel-section">
            <div className="sec-label">{ticket.source.toUpperCase()} {ticket.key}</div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {ticket.url ? <a className="evidence" href={ticket.url} target="_blank" rel="noreferrer">{ticket.title}</a> : ticket.title}
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {ticket.type && <span className="kind-badge">{ticket.type}</span>}
              {ticket.status && <span className="kind-badge">{ticket.status}</span>}
            </div>
          </div>
        )}

        {(busy || acts.length > 0) && !proposal && (
          <div className="msg bot"><div className="bubble">
            {busy && acts.length === 0 && <span className="chat-thinking"><i /><i /><i /></span>}
            {acts.length > 0 && <div className="activity-line"><Icon.check />{acts.join(" · ")}</div>}
          </div></div>
        )}

        {proposal && (
          <FixCard
            p={proposal} source={source} ticket={ticket}
            acts={acts} onChip={onChip} onOpenCause={openCause}
            peek={peek} wsId={wsId}
            onCopy={copyPrompt} copied={copied}
            onPost={postComment} posting={posting} posted={posted}
          />
        )}
      </div>
    </div>
  );
}

const CONF_HUE: Record<string, string> = { high: "--l-table", medium: "--l-service", low: "--l-controller" };

function FixCard({ p, source, ticket, acts, onChip, onOpenCause, peek, wsId, onCopy, copied, onPost, posting, posted }: {
  p: FixProposal;
  source: Source;
  ticket: Ticket | null;
  acts: string[];
  onChip: (id: string) => void;
  onOpenCause: (file: string, line: number, nodeId?: string) => void;
  peek: { ev: Evidence; projectId: string } | null;
  wsId: string;
  onCopy: () => void;
  copied: boolean;
  onPost: () => void;
  posting: boolean;
  posted: string | null;
}) {
  return (
    <div className="ai-card" style={{ marginTop: 4 }}>
      <div className="ai-head">
        <Icon.spark style={{ width: 14, height: 14, color: "var(--brand)" }} />
        <span>Suggested fix</span>
        <span className="kind-badge" style={{ marginLeft: "auto", background: `color-mix(in srgb, var(${CONF_HUE[p.confidence]}) 18%, transparent)` }}>
          {p.confidence} confidence
        </span>
      </div>

      <div className="ai-sec"><h5>Problem</h5><p>{p.problem}</p></div>

      <div className="ai-sec">
        <h5>Root cause</h5>
        {p.root_cause.map((c, i) => (
          <div key={i} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <EvidenceLink ev={{ file: c.file, line: c.line ?? 1, snippet: c.summary }}
                onOpen={() => onOpenCause(c.file, c.line ?? 1, c.node_id)} />
              {c.node_id && (
                <span className="node-chip" onClick={() => onChip(c.node_id!)}>
                  {c.node_id.split(":").pop()}
                </span>
              )}
            </div>
            <p style={{ margin: "3px 0 0" }}>{c.summary}</p>
          </div>
        ))}
        {peek && <CodePeek wsId={wsId} projectId={peek.projectId} ev={peek.ev} />}
      </div>

      <div className="ai-sec"><h5>Proposed fix</h5><p>{p.proposed_fix}</p></div>

      <div className="ai-sec">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h5 style={{ margin: 0 }}>Implementation prompt</h5>
          <button className="tbtn" style={{ marginLeft: "auto", padding: "3px 8px" }} onClick={onCopy}>
            <Icon.check style={{ width: 12, height: 12 }} />{copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="impl-prompt">{p.implementation_prompt}</pre>
        <div className="sub">Paste into your coding agent (Claude Code, Cursor, Copilot…) to implement.</div>
      </div>

      {p.risks.length > 0 && (
        <div className="ai-sec">
          <h5>Risks &amp; unverified</h5>
          <ul>{p.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      )}

      {source !== "manual" && ticket && (
        <div className="ai-sec">
          {posted ? (
            <div className="activity-line"><Icon.check />Posted to{" "}
              <a className="evidence" href={posted} target="_blank" rel="noreferrer">{ticket.key}</a></div>
          ) : (
            <button className="tbtn" onClick={onPost} disabled={posting}>
              <Icon.send style={{ width: 12, height: 12 }} />
              {posting ? "Posting…" : `Post as comment on ${ticket.key}`}
            </button>
          )}
        </div>
      )}
      {acts.length > 0 && <div className="activity-line" style={{ marginTop: 10 }}><Icon.check />{acts.join(" · ")}</div>}
    </div>
  );
}
