import { useEffect, useState } from "react";
import { api, type Settings, type TrackerStatus } from "../api";
import { Icon, Spinner } from "../icons";

export function SettingsModal({ onClose, onChanged }: {
  onClose: () => void;
  onChanged: (llmEnabled: boolean) => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  const refresh = async () => {
    const s = await api.getSettings();
    setSettings(s);
    onChanged(s.llm_enabled);
  };
  useEffect(() => { void refresh(); /* eslint-disable-line react-hooks/exhaustive-deps */ }, []);

  const save = async () => {
    if (!key.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const s = await api.setApiKey(key.trim());
      setSettings(s);
      onChanged(s.llm_enabled);
      setKey("");
      setSavedFlash(true);
      setTimeout(() => setSavedFlash(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setError(null);
    try {
      const s = await api.clearApiKey();
      setSettings(s);
      onChanged(s.llm_enabled);
    } finally {
      setBusy(false);
    }
  };

  const setProvider = async (p: "auto" | "anthropic" | "claude-cli") => {
    setBusy(true);
    try {
      const s = await api.setAiProvider(p);
      setSettings(s);
      onChanged(s.llm_enabled);
    } finally {
      setBusy(false);
    }
  };

  const statusText = !settings ? "…"
    : settings.effective_provider === "claude-cli" ? "AI enabled — using your local Claude CLI (no key)"
    : settings.key_source === "stored" ? `AI enabled — using your key (${settings.stored_key_preview})`
    : settings.key_source === "env" ? "AI enabled — using the backend environment key"
    : "AI disabled — choose a provider below";
  const statusColor = settings?.llm_enabled ? "var(--reads)" : "var(--writes)";

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <Icon.settings style={{ width: 16, height: 16, color: "var(--ink-3)" }} />
          <span style={{ fontWeight: 600, fontSize: 14.5 }}>Settings</span>
          <button className="panel-close" onClick={onClose}><Icon.x /></button>
        </div>

        <div className="modal-row">
          <span className="modal-dot" style={{ background: statusColor }} />
          <span style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{statusText}</span>
        </div>

        <div className="sec-label" style={{ marginTop: 16 }}>AI answers use</div>
        <div className="suggest-row" style={{ marginBottom: 6 }}>
          {([["auto", "Auto"], ["anthropic", "Anthropic key"], ["claude-cli", "Local Claude CLI"]] as const).map(([v, label]) => {
            const disabled = v === "claude-cli" && !settings?.claude_cli;
            const on = settings?.ai_provider === v;
            return (
              <span key={v} className={"suggest" + (on ? " on" : "")}
                style={{ opacity: disabled ? 0.4 : 1, pointerEvents: disabled || busy ? "none" : "auto" }}
                onClick={() => setProvider(v)}>{label}</span>
            );
          })}
        </div>
        <p style={{ margin: "0 0 4px", fontSize: 11.5, color: "var(--ink-3)", lineHeight: 1.5 }}>
          {settings?.claude_cli
            ? "Local Claude CLI detected — uses your Claude subscription, no API key needed."
            : "Local Claude CLI not detected — install it, or use an Anthropic key below."}
        </p>

        <div className="sec-label" style={{ marginTop: 16 }}>Anthropic API key</div>
        <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--ink-3)", lineHeight: 1.5 }}>
          Bring your own key to test AI summaries, chat, and guided tours. It is validated with a
          free token-count call, stored in the local database, and used only by your backend.
        </p>
        <div className="chat-input" style={{ marginBottom: 10 }}>
          <input
            type="password"
            placeholder="sk-ant-…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void save()}
          />
        </div>
        {error && (
          <div style={{ fontSize: 11.5, color: "var(--writes)", fontFamily: "var(--mono)", marginBottom: 10 }}>
            {error}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="drop-btn" style={{ margin: 0, height: 32, padding: "0 14px", fontSize: 12.5 }}
            onClick={() => void save()} disabled={busy || !key.trim()}>
            {busy ? <Spinner size={13} /> : <Icon.check style={{ width: 13, height: 13 }} />}
            Save &amp; validate
          </button>
          {settings?.key_source === "stored" && (
            <button className="tbtn" onClick={() => void clear()} disabled={busy}>Clear stored key</button>
          )}
          {savedFlash && <span style={{ fontSize: 12, color: "var(--reads)" }}>Key validated ✓</span>}
        </div>

        <TrackerSettings />

        <div className="modal-row" style={{ marginTop: 18, borderTop: "1px solid var(--line-2)", paddingTop: 12 }}>
          <span style={{ fontSize: 11.5, color: "var(--ink-3)" }}>Model</span>
          <span className="mono" style={{ fontSize: 11.5, marginLeft: "auto", color: "var(--ink-2)" }}>
            {settings?.model ?? "…"}
          </span>
        </div>
      </div>
    </div>
  );
}

function TrackerSettings() {
  const [st, setSt] = useState<TrackerStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [jira, setJira] = useState({ base_url: "", email: "", api_token: "" });
  const [ado, setAdo] = useState({ org: "", project: "", pat: "" });

  const refresh = () => api.trackersStatus().then(setSt).catch(() => undefined);
  useEffect(() => { void refresh(); }, []);

  async function run(name: string, fn: () => Promise<TrackerStatus>) {
    setBusy(name);
    setErr(null);
    try { setSt(await fn()); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  }

  return (
    <div style={{ marginTop: 18, borderTop: "1px solid var(--line-2)", paddingTop: 14 }}>
      <div className="sec-label">Issue trackers</div>
      <p style={{ margin: "0 0 12px", fontSize: 12, color: "var(--ink-3)", lineHeight: 1.5 }}>
        Connect Jira or Azure DevOps to analyze a ticket and get an evidence-grounded fix. Credentials
        are validated, stored in the local database, and used only by your backend.
      </p>
      {err && (
        <div style={{ fontSize: 11.5, color: "var(--writes)", fontFamily: "var(--mono)", marginBottom: 10 }}>{err}</div>
      )}

      {/* Jira */}
      <div className="modal-row" style={{ marginBottom: 8 }}>
        <span className="modal-dot" style={{ background: st?.jira.configured ? "var(--reads)" : "var(--ink-4)" }} />
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Jira</span>
        {st?.jira.configured && (
          <span className="mono" style={{ fontSize: 11, marginLeft: "auto", color: "var(--ink-3)" }}>
            {st.jira.email} · connected
          </span>
        )}
      </div>
      {st?.jira.configured ? (
        <button className="tbtn" style={{ marginBottom: 14 }} disabled={busy === "jira-clear"}
          onClick={() => void run("jira-clear", api.clearJira)}>Disconnect Jira</button>
      ) : (
        <div style={{ display: "grid", gap: 7, marginBottom: 14 }}>
          <input className="ti" placeholder="https://your-domain.atlassian.net" value={jira.base_url}
            onChange={(e) => setJira({ ...jira, base_url: e.target.value })} />
          <input className="ti" placeholder="you@company.com" value={jira.email}
            onChange={(e) => setJira({ ...jira, email: e.target.value })} />
          <input className="ti" type="password" placeholder="API token" value={jira.api_token}
            onChange={(e) => setJira({ ...jira, api_token: e.target.value })} />
          <button className="btn-primary" style={{ justifySelf: "start" }} disabled={busy === "jira"}
            onClick={() => void run("jira", () => api.setJira(jira))}>
            {busy === "jira" ? "Connecting…" : "Connect Jira"}
          </button>
        </div>
      )}

      {/* Azure DevOps */}
      <div className="modal-row" style={{ marginBottom: 8 }}>
        <span className="modal-dot" style={{ background: st?.ado.configured ? "var(--reads)" : "var(--ink-4)" }} />
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>Azure DevOps</span>
        {st?.ado.configured && (
          <span className="mono" style={{ fontSize: 11, marginLeft: "auto", color: "var(--ink-3)" }}>
            {st.ado.org}/{st.ado.project} · connected
          </span>
        )}
      </div>
      {st?.ado.configured ? (
        <button className="tbtn" disabled={busy === "ado-clear"}
          onClick={() => void run("ado-clear", api.clearAdo)}>Disconnect Azure DevOps</button>
      ) : (
        <div style={{ display: "grid", gap: 7 }}>
          <input className="ti" placeholder="Organization (dev.azure.com/<org>)" value={ado.org}
            onChange={(e) => setAdo({ ...ado, org: e.target.value })} />
          <input className="ti" placeholder="Project" value={ado.project}
            onChange={(e) => setAdo({ ...ado, project: e.target.value })} />
          <input className="ti" type="password" placeholder="Personal Access Token" value={ado.pat}
            onChange={(e) => setAdo({ ...ado, pat: e.target.value })} />
          <button className="btn-primary" style={{ justifySelf: "start" }} disabled={busy === "ado"}
            onClick={() => void run("ado", () => api.setAdo(ado))}>
            {busy === "ado" ? "Connecting…" : "Connect Azure DevOps"}
          </button>
        </div>
      )}
    </div>
  );
}
