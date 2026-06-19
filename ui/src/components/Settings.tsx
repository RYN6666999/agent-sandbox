import { useEffect, useState } from "react";
import { getSettings, saveSettings, listModels, AppSettings, McpServer } from "../api";
import { useStore } from "../store";

const DEFAULT: AppSettings = {
  converse_model: "agnes",
  maker_model: "gpt-oss-120b",
  checker_model: "gemini-flash",
  checker_fallbacks: ["agnes"],
  max_rounds: 5,
  temperature: 0.7,
  max_tokens: 2048,
  system_prompt: "",
  mcp_servers: [],
  api_keys: { agnes: "", gemini: "", anthropic: "" },
};

type Tab = "models" | "loop" | "mcp" | "keys";

const TABS: { id: Tab; label: string }[] = [
  { id: "models", label: "Models" },
  { id: "loop",   label: "Loop" },
  { id: "mcp",    label: "MCP" },
  { id: "keys",   label: "API Keys" },
];

export function Settings() {
  const { settingsOpen, setSettingsOpen } = useStore();
  const [tab, setTab] = useState<Tab>("models");
  const [s, setS] = useState<AppSettings>(DEFAULT);
  const [models, setModels] = useState<{ free: string[]; paid: string[] }>({ free: [], paid: [] });
  const [saved, setSaved] = useState(false);
  const [newMcp, setNewMcp] = useState<Omit<McpServer, "enabled">>({ name: "", url: "" });

  useEffect(() => {
    if (!settingsOpen) return;
    getSettings().then((d) => setS({ ...DEFAULT, ...d })).catch(() => {});
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

  const freeOpts = models.free.length ? models.free : ["gpt-oss-120b", "deepseek-v3", "openrouter-classifier"];
  const paidOpts = models.paid.length ? models.paid : ["claude-opus", "claude-sonnet", "gemini-flash", "agnes"];

  const C = {
    bg: "#f2ede6", surface: "#ede8e0", border: "#d4c9bb",
    text1: "#3d352a", text2: "#7d7167", text3: "#a89a8a", text4: "#b5a99a",
  };

  const inp: React.CSSProperties = {
    width: "100%", background: C.surface, border: `0.5px solid ${C.border}`,
    borderRadius: 6, padding: "7px 10px", fontSize: 12, color: C.text1,
    boxSizing: "border-box", fontFamily: "inherit", outline: "none",
  };

  return (
    <>
      <style>{`
        .st-tab:hover { background: #dfd8ce !important; }
        .st-inp:focus { border-color: #a89a8a !important; }
        .st-row:hover .st-del { opacity: 1 !important; }
        .st-ghost:hover { background: #dfd8ce !important; }
      `}</style>

      {/* backdrop */}
      <div
        onClick={() => setSettingsOpen(false)}
        style={{
          position: "fixed", inset: 0, zIndex: 200,
          background: "rgba(61,53,42,.3)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}
      >
        {/* panel — explicit height so flex children work */}
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            width: 660, height: "72vh",
            borderRadius: 12, overflow: "hidden",
            background: C.bg, border: `0.5px solid ${C.border}`,
            display: "flex", flexDirection: "column",
            boxShadow: "0 24px 64px rgba(61,53,42,.18)",
          }}
        >
          {/* header */}
          <div style={{
            padding: "14px 20px", borderBottom: `0.5px solid ${C.border}`,
            display: "flex", alignItems: "center", flexShrink: 0,
          }}>
            <span style={{ fontSize: 14, fontWeight: 500, color: C.text1, flex: 1 }}>Settings</span>
            <button onClick={() => setSettingsOpen(false)} style={{
              background: "none", border: "none", cursor: "pointer",
              color: C.text4, fontSize: 16, lineHeight: 1, padding: 4,
            }}>✕</button>
          </div>

          {/* body */}
          <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
            {/* left nav */}
            <div style={{
              width: 148, background: C.surface,
              borderRight: `0.5px solid ${C.border}`,
              padding: "10px 8px", flexShrink: 0,
              display: "flex", flexDirection: "column", gap: 2,
            }}>
              {TABS.map((t) => (
                <button key={t.id} className="st-tab" onClick={() => setTab(t.id)} style={{
                  width: "100%", background: tab === t.id ? "#d9d1c5" : "transparent",
                  border: "none", borderRadius: 6, padding: "8px 12px", textAlign: "left",
                  cursor: "pointer", fontSize: 12,
                  color: tab === t.id ? C.text1 : C.text2,
                  fontWeight: tab === t.id ? 500 : 400,
                  transition: "background .12s",
                }}>{t.label}</button>
              ))}
            </div>

            {/* content */}
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 22px", display: "flex", flexDirection: "column", gap: 20 }}>

              {/* ── Models ── */}
              {tab === "models" && <>
                <Field label="Converse model" hint="閒聊用，快速便宜">
                  <ModelSelect value={s.converse_model ?? "gemini-flash"} onChange={(v) => patch({ converse_model: v })} free={freeOpts} paid={paidOpts} style={inp} />
                </Field>
                <Field label="Maker model" hint="執行任務的主力模型">
                  <ModelSelect value={s.maker_model} onChange={(v) => patch({ maker_model: v })} free={freeOpts} paid={paidOpts} style={inp} />
                </Field>
                <Field label="Checker model" hint="評分反饋的模型">
                  <ModelSelect value={s.checker_model} onChange={(v) => patch({ checker_model: v })} free={freeOpts} paid={paidOpts} style={inp} />
                </Field>
                <Field label="Checker fallbacks" hint="Checker 失敗時依序嘗試（點選切換）">
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {[...freeOpts, ...paidOpts].filter((m) => m !== s.checker_model).map((m) => {
                      const on = s.checker_fallbacks.includes(m);
                      return (
                        <button key={m} onClick={() => patch({
                          checker_fallbacks: on
                            ? s.checker_fallbacks.filter((x) => x !== m)
                            : [...s.checker_fallbacks, m],
                        })} style={{
                          padding: "4px 11px", borderRadius: 20,
                          background: on ? C.text1 : C.surface,
                          color: on ? C.bg : C.text2,
                          border: `0.5px solid ${on ? C.text1 : C.border}`,
                          fontSize: 11, cursor: "pointer", transition: "all .12s",
                        }}>{m}</button>
                      );
                    })}
                  </div>
                </Field>
                <Field label="System prompt" hint="每次注入給 Maker 的額外指令">
                  <textarea
                    className="st-inp"
                    value={s.system_prompt ?? ""}
                    onChange={(e) => patch({ system_prompt: e.target.value })}
                    rows={4}
                    placeholder="You are a focused implementer…"
                    style={{ ...inp, resize: "vertical", lineHeight: 1.6 }}
                  />
                </Field>
              </>}

              {/* ── Loop ── */}
              {tab === "loop" && <>
                <Field label={`Max rounds — ${s.max_rounds}`} hint="Maker/Checker 最多跑幾輪">
                  <input type="range" min={1} max={10} step={1} value={s.max_rounds}
                    onChange={(e) => patch({ max_rounds: +e.target.value })}
                    style={{ width: "100%", accentColor: C.text1 }} />
                  <Row3 left="1" right="10" />
                </Field>
                <Field label={`Temperature — ${s.temperature.toFixed(1)}`} hint="生成隨機性">
                  <input type="range" min={0} max={1} step={0.1} value={s.temperature}
                    onChange={(e) => patch({ temperature: +e.target.value })}
                    style={{ width: "100%", accentColor: C.text1 }} />
                  <Row3 left="0 精確" right="1 創意" />
                </Field>
                <Field label={`Max tokens — ${s.max_tokens}`} hint="每輪 Maker 輸出上限">
                  <input type="range" min={256} max={8192} step={256} value={s.max_tokens}
                    onChange={(e) => patch({ max_tokens: +e.target.value })}
                    style={{ width: "100%", accentColor: C.text1 }} />
                  <Row3 left="256" right="8192" />
                </Field>
              </>}

              {/* ── MCP ── */}
              {tab === "mcp" && <>
                <div style={{ fontSize: 11, color: C.text3, lineHeight: 1.7 }}>
                  Model Context Protocol 伺服器讓 Agent 可呼叫外部工具。<br />
                  GBrain 預設在 <code style={{ fontSize: 10 }}>http://localhost:7788</code> 提供 query / search / get_page 等工具。
                </div>

                {s.mcp_servers.length === 0 && (
                  <div style={{ fontSize: 12, color: C.text4 }}>尚無 MCP 伺服器</div>
                )}

                {s.mcp_servers.map((m, i) => (
                  <div key={i} className="st-row" style={{
                    background: C.surface, border: `0.5px solid ${C.border}`,
                    borderRadius: 8, padding: "10px 12px",
                    display: "flex", alignItems: "center", gap: 10,
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12, color: C.text1, fontWeight: 500 }}>{m.name}</div>
                      <div style={{ fontSize: 11, color: C.text3, marginTop: 1 }}>{m.url}</div>
                    </div>
                    {/* toggle */}
                    <div onClick={() => {
                      patch({ mcp_servers: s.mcp_servers.map((x, idx) => idx === i ? { ...x, enabled: !x.enabled } : x) });
                    }} style={{
                      width: 36, height: 20, borderRadius: 10, cursor: "pointer",
                      background: m.enabled ? C.text1 : C.border,
                      position: "relative", flexShrink: 0, transition: "background .15s",
                    }}>
                      <span style={{
                        position: "absolute", top: 2,
                        left: m.enabled ? 18 : 2,
                        width: 16, height: 16, borderRadius: "50%",
                        background: "#f2ede6", transition: "left .15s",
                      }} />
                    </div>
                    <button className="st-del" onClick={() => patch({ mcp_servers: s.mcp_servers.filter((_, idx) => idx !== i) })} style={{
                      opacity: 0, background: "none", border: "none",
                      color: C.text4, cursor: "pointer", fontSize: 14, transition: "opacity .15s",
                    }}>✕</button>
                  </div>
                ))}

                {/* add row */}
                <div style={{
                  background: C.surface, border: `0.5px dashed ${C.border}`,
                  borderRadius: 8, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8,
                }}>
                  <div style={{ fontSize: 10, color: C.text4, textTransform: "uppercase", letterSpacing: ".05em" }}>Add MCP server</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="st-inp" placeholder="Name" value={newMcp.name}
                      onChange={(e) => setNewMcp((p) => ({ ...p, name: e.target.value }))}
                      style={{ ...inp, flex: 1 }} />
                    <input className="st-inp" placeholder="http://localhost:3001" value={newMcp.url}
                      onChange={(e) => setNewMcp((p) => ({ ...p, url: e.target.value }))}
                      style={{ ...inp, flex: 2 }} />
                    <button onClick={addMcp} style={{
                      background: C.text1, color: C.bg, border: "none",
                      borderRadius: 6, padding: "0 14px", cursor: "pointer",
                      fontSize: 12, fontWeight: 500, flexShrink: 0,
                    }}>Add</button>
                  </div>
                  <button onClick={() => {
                    setNewMcp({ name: "GBrain", url: "http://localhost:7788" });
                  }} style={{
                    alignSelf: "flex-start", background: "none", border: `0.5px solid ${C.border}`,
                    borderRadius: 5, padding: "4px 10px", cursor: "pointer",
                    fontSize: 11, color: C.text3,
                  }}>＋ 快速加入 GBrain</button>
                </div>
              </>}

              {/* ── API Keys ── */}
              {tab === "keys" && <>
                <div style={{ fontSize: 11, color: C.text3, lineHeight: 1.7 }}>
                  金鑰僅暫存於後端執行環境，不寫入磁碟。<br />
                  永久保存請在 <code style={{ fontSize: 10 }}>.env</code> 檔案中設定。
                </div>
                {[
                  { key: "agnes",       label: "Agnes API Key",       env: "AGNES_API_KEY" },
                  { key: "gemini",      label: "Gemini API Key",       env: "GEMINI_API_KEY" },
                  { key: "anthropic",   label: "Anthropic API Key",    env: "ANTHROPIC_API_KEY" },
                  { key: "openrouter",  label: "OpenRouter API Key",   env: "OPENROUTER_API_KEY" },
                ].map(({ key, label, env }) => (
                  <Field key={key} label={label} hint={env}>
                    <input className="st-inp" type="password" placeholder="sk-…"
                      value={s.api_keys?.[key] ?? ""}
                      onChange={(e) => patch({ api_keys: { ...s.api_keys, [key]: e.target.value } })}
                      style={inp} />
                  </Field>
                ))}
              </>}

            </div>
          </div>

          {/* footer */}
          <div style={{
            padding: "11px 20px", borderTop: `0.5px solid ${C.border}`,
            background: C.surface, display: "flex", justifyContent: "flex-end", gap: 8, flexShrink: 0,
          }}>
            <button className="st-ghost" onClick={() => setSettingsOpen(false)} style={{
              background: C.bg, color: C.text2, border: `0.5px solid ${C.border}`,
              borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontSize: 12,
            }}>Cancel</button>
            <button onClick={handleSave} style={{
              background: saved ? "#eef3e8" : C.text1,
              color: saved ? "#7a8c5e" : C.bg,
              border: saved ? "0.5px solid #b5c9a0" : "none",
              borderRadius: 6, padding: "7px 18px", cursor: "pointer", fontSize: 12, fontWeight: 500,
              transition: "all .15s",
            }}>{saved ? "✓ Saved" : "Save"}</button>
          </div>
        </div>
      </div>
    </>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 12, color: "#3d352a", fontWeight: 500, marginBottom: 3 }}>{label}</div>
      {hint && <div style={{ fontSize: 11, color: "#b5a99a", marginBottom: 7 }}>{hint}</div>}
      {children}
    </div>
  );
}

function ModelSelect({ value, onChange, free, paid, style }: {
  value: string;
  onChange: (v: string) => void;
  free: string[];
  paid: string[];
  style: React.CSSProperties;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="st-inp" style={style}>
      <optgroup label="免費">
        {free.map((o) => <option key={o} value={o}>{o}</option>)}
      </optgroup>
      <optgroup label="付費">
        {paid.map((o) => <option key={o} value={o}>{o}</option>)}
      </optgroup>
    </select>
  );
}

function Row3({ left, right }: { left: string; right: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#c4bfb8", marginTop: 3 }}>
      <span>{left}</span><span>{right}</span>
    </div>
  );
}
