import { useEffect, useState } from "react";
import { getSettings, saveSettings, listModels, AppSettings, McpServer } from "../api";
import { useStore } from "../store";

const DEFAULT: AppSettings = {
  maker_model: "agnes",
  checker_model: "gemini-flash",
  checker_fallbacks: ["agnes"],
  max_rounds: 5,
  temperature: 0.7,
  max_tokens: 2048,
  mcp_servers: [],
  api_keys: { agnes: "", gemini: "", anthropic: "" },
};

type Tab = "models" | "loop" | "mcp" | "keys";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "models", label: "Models", icon: "ti-brain" },
  { id: "loop",   label: "Loop",   icon: "ti-refresh" },
  { id: "mcp",    label: "MCP",    icon: "ti-plug" },
  { id: "keys",   label: "API Keys", icon: "ti-key" },
];

export function Settings() {
  const { settingsOpen, setSettingsOpen } = useStore();
  const [tab, setTab] = useState<Tab>("models");
  const [s, setS] = useState<AppSettings>(DEFAULT);
  const [models, setModels] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [newMcp, setNewMcp] = useState<Omit<McpServer, "enabled">>({ name: "", url: "" });

  useEffect(() => {
    if (!settingsOpen) return;
    getSettings().then(setS).catch(() => {});
    listModels().then(setModels).catch(() => {});
  }, [settingsOpen]);

  if (!settingsOpen) return null;

  function patch(p: Partial<AppSettings>) { setS((prev) => ({ ...prev, ...p })); }

  async function handleSave() {
    await saveSettings(s);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  function addMcp() {
    if (!newMcp.name || !newMcp.url) return;
    patch({ mcp_servers: [...s.mcp_servers, { ...newMcp, enabled: true }] });
    setNewMcp({ name: "", url: "" });
  }

  function toggleMcp(i: number) {
    const updated = s.mcp_servers.map((m, idx) => idx === i ? { ...m, enabled: !m.enabled } : m);
    patch({ mcp_servers: updated });
  }

  function removeMcp(i: number) {
    patch({ mcp_servers: s.mcp_servers.filter((_, idx) => idx !== i) });
  }

  const modelOptions = models.length ? models : ["agnes", "gemini-flash", "claude-sonnet", "ollama-local"];

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 200,
      background: "rgba(61,53,42,.35)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }} onClick={() => setSettingsOpen(false)}>
      <style>{`
        @keyframes settingsIn { from{opacity:0;transform:scale(.97)} to{opacity:1;transform:scale(1)} }
        .settings-panel { animation: settingsIn .2s ease; }
        .stab { transition: background .12s, color .12s; cursor: pointer; }
        .stab:hover { background: #dfd8ce !important; }
        .s-input { outline: none; transition: border-color .15s; font-family: inherit; }
        .s-input:focus { border-color: #a89a8a !important; }
        .toggle { cursor: pointer; transition: background .15s; }
        .s-row:hover .del-mcp { opacity: 1 !important; }
      `}</style>

      <div className="settings-panel" onClick={(e) => e.stopPropagation()} style={{
        width: 640, maxHeight: "80vh", borderRadius: 12,
        background: "#f2ede6", border: "0.5px solid #d4c9bb",
        display: "flex", flexDirection: "column", overflow: "hidden",
        boxShadow: "0 20px 60px rgba(61,53,42,.2)",
      }}>
        {/* header */}
        <div style={{
          padding: "16px 20px", borderBottom: "0.5px solid #d4c9bb",
          display: "flex", alignItems: "center",
        }}>
          <span style={{ fontSize: 14, fontWeight: 500, color: "#3d352a", flex: 1 }}>Settings</span>
          <button onClick={() => setSettingsOpen(false)} style={{
            background: "none", border: "none", cursor: "pointer",
            color: "#b5a99a", fontSize: 16, lineHeight: 1, padding: 4,
          }}>✕</button>
        </div>

        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          {/* left nav */}
          <div style={{
            width: 160, borderRight: "0.5px solid #d4c9bb",
            background: "#ede8e0", padding: "10px 8px", flexShrink: 0,
          }}>
            {TABS.map((t) => (
              <button key={t.id} className="stab" onClick={() => setTab(t.id)} style={{
                width: "100%", background: tab === t.id ? "#d9d1c5" : "transparent",
                border: "none", borderRadius: 6, padding: "8px 10px", textAlign: "left",
                display: "flex", alignItems: "center", gap: 8, marginBottom: 2,
              }}>
                <i className={`ti ${t.icon}`} style={{ fontSize: 15, color: tab === t.id ? "#3d352a" : "#a89a8a" }} aria-hidden="true" />
                <span style={{ fontSize: 12, color: tab === t.id ? "#3d352a" : "#7d7167", fontWeight: tab === t.id ? 500 : 400 }}>
                  {t.label}
                </span>
              </button>
            ))}
          </div>

          {/* content */}
          <div style={{ flex: 1, overflowY: "auto", padding: "18px 20px" }}>

            {/* ── Models ── */}
            {tab === "models" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                <Section label="Maker model" desc="執行任務的主力模型">
                  <Select value={s.maker_model} options={modelOptions} onChange={(v) => patch({ maker_model: v })} />
                </Section>
                <Section label="Checker model" desc="評分與反饋的模型">
                  <Select value={s.checker_model} options={modelOptions} onChange={(v) => patch({ checker_model: v })} />
                </Section>
                <Section label="Checker fallbacks" desc="Checker 失敗時依序嘗試">
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {modelOptions.filter((m) => m !== s.checker_model).map((m) => {
                      const on = s.checker_fallbacks.includes(m);
                      return (
                        <button key={m} onClick={() => patch({
                          checker_fallbacks: on
                            ? s.checker_fallbacks.filter((x) => x !== m)
                            : [...s.checker_fallbacks, m],
                        })} style={{
                          padding: "4px 10px", borderRadius: 20,
                          background: on ? "#3d352a" : "#ede8e0",
                          color: on ? "#f2ede6" : "#7d7167",
                          border: `0.5px solid ${on ? "#3d352a" : "#d4c9bb"}`,
                          fontSize: 11, cursor: "pointer", transition: "all .15s",
                        }}>{m}</button>
                      );
                    })}
                  </div>
                </Section>
              </div>
            )}

            {/* ── Loop ── */}
            {tab === "loop" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
                <Section label="Max rounds" desc={`最多跑幾輪 Maker/Checker（目前 ${s.max_rounds}）`}>
                  <input type="range" min={1} max={10} step={1} value={s.max_rounds}
                    onChange={(e) => patch({ max_rounds: +e.target.value })}
                    style={{ width: "100%", accentColor: "#3d352a" }} />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#b5a99a", marginTop: 2 }}>
                    <span>1</span><span>10</span>
                  </div>
                </Section>
                <Section label="Temperature" desc={`生成隨機性（目前 ${s.temperature.toFixed(1)}）`}>
                  <input type="range" min={0} max={1} step={0.1} value={s.temperature}
                    onChange={(e) => patch({ temperature: +e.target.value })}
                    style={{ width: "100%", accentColor: "#3d352a" }} />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#b5a99a", marginTop: 2 }}>
                    <span>0 精確</span><span>1 創意</span>
                  </div>
                </Section>
                <Section label="Max tokens" desc={`每次生成上限（目前 ${s.max_tokens}）`}>
                  <input type="range" min={256} max={8192} step={256} value={s.max_tokens}
                    onChange={(e) => patch({ max_tokens: +e.target.value })}
                    style={{ width: "100%", accentColor: "#3d352a" }} />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#b5a99a", marginTop: 2 }}>
                    <span>256</span><span>8192</span>
                  </div>
                </Section>
              </div>
            )}

            {/* ── MCP ── */}
            {tab === "mcp" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ fontSize: 11, color: "#a89a8a", lineHeight: 1.6 }}>
                  MCP（Model Context Protocol）伺服器讓 Agent 可以呼叫外部工具。<br />
                  每個 server 需提供名稱與 HTTP 端點 URL。
                </div>
                {s.mcp_servers.length === 0 && (
                  <div style={{ fontSize: 12, color: "#c4bfb8", padding: "8px 0" }}>尚無 MCP 伺服器</div>
                )}
                {s.mcp_servers.map((m, i) => (
                  <div key={i} className="s-row" style={{
                    background: "#ede8e0", border: "0.5px solid #d4c9bb",
                    borderRadius: 8, padding: "10px 12px",
                    display: "flex", alignItems: "center", gap: 10,
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: "#3d352a", fontWeight: 500 }}>{m.name}</div>
                      <div style={{ fontSize: 11, color: "#a89a8a", marginTop: 1 }}>{m.url}</div>
                    </div>
                    <button className="toggle" onClick={() => toggleMcp(i)} style={{
                      width: 36, height: 20, borderRadius: 10,
                      background: m.enabled ? "#3d352a" : "#d4c9bb",
                      border: "none", position: "relative",
                    }}>
                      <span style={{
                        position: "absolute", top: 2,
                        left: m.enabled ? 18 : 2,
                        width: 16, height: 16, borderRadius: "50%",
                        background: "#f2ede6", transition: "left .15s",
                      }} />
                    </button>
                    <button className="del-mcp" onClick={() => removeMcp(i)} style={{
                      opacity: 0, background: "none", border: "none",
                      color: "#b5a99a", cursor: "pointer", fontSize: 14, transition: "opacity .15s",
                    }}>✕</button>
                  </div>
                ))}
                {/* add new */}
                <div style={{
                  background: "#ede8e0", border: "0.5px dashed #d4c9bb",
                  borderRadius: 8, padding: "12px 14px",
                  display: "flex", flexDirection: "column", gap: 8,
                }}>
                  <div style={{ fontSize: 11, color: "#b5a99a", fontWeight: 500 }}>Add MCP server</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="s-input" placeholder="Name" value={newMcp.name}
                      onChange={(e) => setNewMcp((p) => ({ ...p, name: e.target.value }))}
                      style={inputStyle} />
                    <input className="s-input" placeholder="http://localhost:3001" value={newMcp.url}
                      onChange={(e) => setNewMcp((p) => ({ ...p, url: e.target.value }))}
                      style={{ ...inputStyle, flex: 2 }} />
                    <button onClick={addMcp} style={{
                      background: "#3d352a", color: "#f2ede6", border: "none",
                      borderRadius: 6, padding: "0 14px", cursor: "pointer", fontSize: 12, flexShrink: 0,
                    }}>Add</button>
                  </div>
                </div>
              </div>
            )}

            {/* ── API Keys ── */}
            {tab === "keys" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ fontSize: 11, color: "#a89a8a", lineHeight: 1.6 }}>
                  金鑰僅暫存於後端執行環境，不寫入磁碟。重啟後需重新輸入，或在 <code style={{ fontSize: 10 }}>.env</code> 設定。
                </div>
                {[
                  { key: "agnes",     label: "Agnes API Key",     env: "AGNES_API_KEY" },
                  { key: "gemini",    label: "Gemini API Key",    env: "GEMINI_API_KEY" },
                  { key: "anthropic", label: "Anthropic API Key", env: "ANTHROPIC_API_KEY" },
                ].map(({ key, label, env }) => (
                  <Section key={key} label={label} desc={env}>
                    <input className="s-input" type="password" placeholder="sk-…"
                      value={s.api_keys[key] ?? ""}
                      onChange={(e) => patch({ api_keys: { ...s.api_keys, [key]: e.target.value } })}
                      style={inputStyle} />
                  </Section>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* footer */}
        <div style={{
          padding: "12px 20px", borderTop: "0.5px solid #d4c9bb",
          display: "flex", justifyContent: "flex-end", gap: 8,
          background: "#ede8e0",
        }}>
          <button onClick={() => setSettingsOpen(false)} style={ghostBtn}>Cancel</button>
          <button onClick={handleSave} style={{
            ...ghostBtn,
            background: saved ? "#eef3e8" : "#3d352a",
            color: saved ? "#7a8c5e" : "#f2ede6",
            border: saved ? "0.5px solid #b5c9a0" : "none",
          }}>
            {saved ? "✓ Saved" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function Section({ label, desc, children }: { label: string; desc?: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: "#3d352a", fontWeight: 500, marginBottom: 3 }}>{label}</div>
      {desc && <div style={{ fontSize: 11, color: "#b5a99a", marginBottom: 8 }}>{desc}</div>}
      {children}
    </div>
  );
}

function Select({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{
      ...inputStyle, appearance: "none",
      backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23a89a8a'/%3E%3C/svg%3E")`,
      backgroundRepeat: "no-repeat", backgroundPosition: "right 10px center",
      paddingRight: 28, cursor: "pointer",
    }}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", background: "#ede8e0",
  border: "0.5px solid #d4c9bb", borderRadius: 6,
  padding: "7px 10px", fontSize: 12, color: "#3d352a",
  boxSizing: "border-box",
};

const ghostBtn: React.CSSProperties = {
  background: "#ede8e0", color: "#7d7167",
  border: "0.5px solid #d4c9bb", borderRadius: 6,
  padding: "7px 16px", cursor: "pointer", fontSize: 12, fontWeight: 500,
};
