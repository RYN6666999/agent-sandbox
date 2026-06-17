import { useStore } from "../store";

export function RoundsDrawer() {
  const { activeTask, roundsOpen, setRoundsOpen } = useStore();
  const task = activeTask();

  if (!task || task.status === "idle") return null;

  const { history, logs } = task;
  const best = history.length ? Math.max(...history.map((h) => h.score)) : null;

  return (
    <div style={{ borderTop: "0.5px solid #d4c9bb", background: "#e8e1d8", flexShrink: 0 }}>
      <style>{`
        @keyframes cardIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
        .r-card { animation: cardIn .15s ease; }
      `}</style>

      {/* header toggle */}
      <button onClick={() => setRoundsOpen(!roundsOpen)} style={{
        width: "100%", background: "none", border: "none", cursor: "pointer",
        display: "flex", alignItems: "center", gap: 8, padding: "9px 16px",
        transition: "background .15s",
      }}
        onMouseOver={(e) => (e.currentTarget.style.background = "#dfd8ce")}
        onMouseOut={(e) => (e.currentTarget.style.background = "none")}
      >
        <span style={{ fontSize: 11, color: "#7d7167", flex: 1, textAlign: "left" }}>
          Round history {history.length > 0 ? `· ${history.length} rounds` : ""}
        </span>
        {best !== null && (
          <span style={{ fontSize: 11, color: best >= 7 ? "#7a8c5e" : "#c9a96e", fontWeight: 500 }}>
            Best {best.toFixed(1)} / 10
          </span>
        )}
        <span style={{ fontSize: 11, color: "#b5a99a" }}>{roundsOpen ? "▲" : "▼"}</span>
      </button>

      {roundsOpen && (
        <div style={{ display: "flex", gap: 1, background: "#d4c9bb", overflow: "hidden" }}>
          {/* rounds */}
          <div style={{ flex: 1, background: "#ede8e0", overflowY: "auto", maxHeight: 220, padding: "12px 14px" }}>
            <div style={{ fontSize: 10, color: "#b5a99a", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10 }}>
              Checker rounds
            </div>
            {history.length === 0
              ? <div style={{ fontSize: 12, color: "#c4bfb8" }}>等待第一輪…</div>
              : history.map((h) => (
                <div key={h.round} className="r-card" style={{
                  background: "#e8e1d8", border: "0.5px solid #d4c9bb",
                  borderLeft: `2px solid ${h.passed ? "#7a8c5e" : h.score >= 5 ? "#c9a96e" : "#b87c4c"}`,
                  borderRadius: 6, padding: "8px 12px", marginBottom: 8,
                }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
                    <span style={{ fontSize: 11, color: "#a89a8a" }}>Round {h.round}</span>
                    <span style={{
                      fontSize: 16, fontWeight: 500,
                      color: h.score >= 7 ? "#7a8c5e" : h.score >= 5 ? "#c9a96e" : "#b87c4c",
                    }}>{h.score.toFixed(1)}</span>
                  </div>
                  <div style={{ height: 3, background: "#d4c9bb", borderRadius: 2, marginBottom: 6 }}>
                    <div style={{
                      height: "100%", borderRadius: 2, transition: "width .6s ease",
                      width: `${h.score * 10}%`,
                      background: h.score >= 7 ? "#7a8c5e" : h.score >= 5 ? "#c9a96e" : "#b87c4c",
                    }} />
                  </div>
                  <div style={{ fontSize: 11, color: "#7d7167", lineHeight: 1.5 }}>{h.feedback}</div>
                </div>
              ))
            }
          </div>

          {/* logs */}
          <div style={{ width: 220, background: "#f2ede6", overflowY: "auto", maxHeight: 220, padding: "12px 14px", fontFamily: "monospace" }}>
            <div style={{ fontSize: 10, color: "#b5a99a", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10 }}>
              Live log
            </div>
            {logs.length === 0
              ? <div style={{ fontSize: 11, color: "#c4bfb8" }}>無日誌</div>
              : logs.map((l, i) => (
                <div key={i} style={{
                  fontSize: 11, marginBottom: 3, lineHeight: 1.5,
                  color: l.includes("error") || l.includes("Error") ? "#a85858"
                       : l.includes("✓") || l.includes("done") ? "#7a8c5e"
                       : "#7d7167",
                }}>
                  <span style={{ color: "#c4bfb8", marginRight: 5 }}>›</span>{l}
                </div>
              ))
            }
          </div>
        </div>
      )}
    </div>
  );
}
