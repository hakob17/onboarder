import { useEffect, useState } from "react";
import { api, type Settings } from "../api";
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

  const statusText = !settings ? "…"
    : settings.key_source === "stored" ? `AI features enabled — using your key (${settings.stored_key_preview})`
    : settings.key_source === "env" ? "AI features enabled — using the backend environment key"
    : "AI features disabled — no API key configured";
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
