import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, chatStream } from "../api";
import { Icon } from "../icons";
import type { DGraph } from "../model";
import { askIdeAi, inVsCode } from "../vscode";

interface ChatMsg {
  role: "user" | "bot";
  text: string;
  activities: string[];
  streaming?: boolean;
}

const CHIP_RE = /\[node:([^\]]+)\]/g;

function prettyActivity(name: string, input: Record<string, any>): string {
  switch (name) {
    case "query_graph": return "Queried graph";
    case "get_node": return `Read ${String(input?.node_id ?? "node").split(":").pop()}`;
    case "trace_paths": return "Traced paths";
    case "read_source": return `Read ${String(input?.file ?? "source").split("/").pop()}`;
    case "search_code": return `Searched code`;
    case "list_projects": return "Listed projects";
    case "focus_view": return "Highlighted on the map";
    default: return name;
  }
}

function renderWithChips(text: string, g: DGraph, onChip: (id: string) => void): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(CHIP_RE.source, "g");
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(<span key={k++}>{text.slice(last, m.index)}</span>);
    const id = m[1];
    const label = g.byId.get(id)?.label ?? id.split(":").pop() ?? id;
    out.push(
      <span key={k++} className="node-chip" onClick={() => onChip(id)}>{label}</span>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<span key={k++}>{text.slice(last)}</span>);
  return out;
}

export function ChatPanel({ wsId, g, llmEnabled, onDirective, onChip, onClose, ask, onAskConsumed }: {
  wsId: string;
  g: DGraph;
  llmEnabled: boolean;
  onDirective: (d: { node_ids: string[]; mode: string }) => void;
  onChip: (id: string) => void;
  onClose: () => void;
  ask?: string | null;
  onAskConsumed?: () => void;
}) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chatHistory(wsId)
      .then((rows) => setMsgs(rows.map((r) => ({
        role: r.role === "user" ? "user" : "bot",
        text: r.content,
        activities: [],
      }))))
      .catch(() => undefined);
  }, [wsId]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [msgs]);

  // question handed in from outside (VS Code "Ask Onboarder" command)
  useEffect(() => {
    if (ask && llmEnabled && !busy) {
      onAskConsumed?.();
      void send(ask);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ask, llmEnabled]);

  const patchLast = (fn: (m: ChatMsg) => ChatMsg) =>
    setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMsgs((ms) => [...ms,
      { role: "user", text: q, activities: [] },
      { role: "bot", text: "", activities: [], streaming: true },
    ]);
    try {
      for await (const ev of chatStream(wsId, q)) {
        if (ev.event === "text_delta") {
          patchLast((m) => ({ ...m, text: m.text + ev.data.text }));
        } else if (ev.event === "tool_started") {
          const label = prettyActivity(ev.data.name, ev.data.input);
          patchLast((m) => ({
            ...m,
            activities: m.activities.includes(label) ? m.activities : [...m.activities, label],
          }));
        } else if (ev.event === "ui_directive") {
          onDirective(ev.data);
        } else if (ev.event === "error") {
          patchLast((m) => ({ ...m, text: m.text || `⚠ ${ev.data.message}`, streaming: false }));
        } else if (ev.event === "done") {
          patchLast((m) => ({ ...m, streaming: false }));
        }
      }
    } finally {
      patchLast((m) => ({ ...m, streaming: false }));
      setBusy(false);
    }
  }

  const endpoints = g.nodes.filter((n) => n.type === "endpoint");
  const tables = g.nodes.filter((n) => n.type === "table");
  const services = g.nodes.filter((n) => n.type === "service" && !n.cross);
  const getEp = endpoints.find((n) => n.method === "GET") ?? endpoints[1];
  const suggestions = [
    endpoints[0] && `Trace ${endpoints[0].method} ${endpoints[0].path}`,
    tables[0] && `Who writes to the ${tables[0].label} table?`,
    getEp && `${getEp.method} ${getEp.path} is slow — where should I look?`,
    services[0] && `What does ${services[0].label} do?`,
  ].filter(Boolean).slice(0, 3) as string[];

  return (
    <div className="chat-dock" onClick={(e) => e.stopPropagation()}>
      <div className="chat-head">
        <Icon.spark className="ai-spark" style={{ color: "var(--brand)" }} />
        <div style={{ flex: 1 }}>
          <div className="ttl">Ask Onboarder</div>
          <div className="sub">Grounded in this workspace's graph</div>
        </div>
        <button className="tbtn icon" onClick={onClose}><Icon.x /></button>
      </div>

      <div className="chat-body" ref={bodyRef}>
        {!llmEnabled && (
          <div className="msg bot"><div className="bubble">
            Chat needs an Anthropic API key — add yours in Settings (gear icon in the left rail).
          </div></div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={"msg " + (m.role === "user" ? "user" : "bot")}>
            <div className="bubble" style={{ whiteSpace: "pre-wrap" }}>
              {m.role === "bot" ? renderWithChips(m.text, g, onChip) : m.text}
              {m.streaming && !m.text && (
                <span className="chat-thinking"><i /><i /><i /></span>
              )}
              {m.streaming && m.text && <span className="cursor-blink" />}
              {m.activities.length > 0 && (
                <div className="activity-line">
                  <Icon.check />{m.activities.join(" · ")}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="chat-foot">
        <div className="suggest-row">
          {suggestions.map((s) => (
            <span key={s} className="suggest" onClick={() => send(s)}>{s}</span>
          ))}
        </div>
        {inVsCode && (
          <button className="suggest" style={{ marginBottom: 8, width: "100%", justifyContent: "center", display: "flex", gap: 6, alignItems: "center" }}
            title="Hand this question to your IDE's AI (Claude Code / AI Assistant / Junie) — uses the IDE's model, no key"
            onClick={() => askIdeAi(input.trim() || "Explain how this system works.")}>
            <Icon.spark style={{ width: 13, height: 13 }} />Ask in IntelliJ AI ↗
          </button>
        )}
        <div className="chat-input">
          <input
            placeholder="Ask about this codebase…"
            value={input}
            disabled={!llmEnabled}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
          />
          <button className="send" onClick={() => send(input)} disabled={busy || !llmEnabled}>
            <Icon.send style={{ width: 14, height: 14 }} />
          </button>
        </div>
      </div>
    </div>
  );
}
