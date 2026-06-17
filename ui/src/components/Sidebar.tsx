import { useStore } from "../store";

const STATUS_DOT: Record<string, string> = {
  idle: "#c4bfb8", aligning: "#c9a96e", running: "#a89a8a",
  done: "#7a8c5e", escalate: "#b87c4c", error: "#a85858",
};

const STATUS_LABEL: Record<string, string> = {
  idle: "待命", aligning: "對齊中", running: "執行中",
  done: "完成", escalate: "需介入", error: "錯誤",
};

export function Sidebar() {
  const { tasks, activeTaskId, newTask, setActiveTask, deleteTask, setSettingsOpen } = useStore();

  return (
    <aside style={{
      width: 210, minWidth: 210,
      background: "#e8e1d8",
      borderRight: "0.5px solid #d4c9bb",
      display: "flex", flexDirection: "column", height: "100%",
    }}>
      <style>{`
        @keyframes taskIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
        @keyframes pulse  { 0%,100%{opacity:1}50%{opacity:.3} }
        .task-row { transition: background .15s; cursor: pointer; }
        .task-row:hover { background: #dfd8ce !important; }
        .task-row:hover .del-x { opacity: 1 !important; }
        .new-task-btn { transition: background .15s; cursor: pointer; }
        .new-task-btn:hover { background: #dfd8ce !important; }
      `}</style>

      {/* logo */}
      <div style={{
        padding: "14px 14px 12px",
        borderBottom: "0.5px solid #d4c9bb",
        display: "flex", alignItems: "center", gap: 9,
      }}>
        <div style={{
          width: 26, height: 26, borderRadius: 6, background: "#3d352a",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0,
        }}>🧠</div>
        <span style={{ fontSize: 13, fontWeight: 500, color: "#3d352a" }}>AgentOS</span>
      </div>

      {/* section label */}
      <div style={{ padding: "10px 14px 6px", fontSize: 10, color: "#b5a99a", letterSpacing: ".07em", textTransform: "uppercase" }}>
        Tasks
      </div>

      {/* task list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "0 6px" }}>
        {tasks.length === 0 && (
          <div style={{ fontSize: 12, color: "#c4bfb8", padding: "10px 8px", textAlign: "center" }}>
            按「新任務」開始
          </div>
        )}
        {tasks.map((t, i) => {
          const active = t.id === activeTaskId;
          return (
            <div key={t.id} className="task-row"
              onClick={() => setActiveTask(t.id)}
              style={{
                background: active ? "#d9d1c5" : "transparent",
                borderRadius: 6, padding: "7px 8px", marginBottom: 1,
                position: "relative",
                animation: `taskIn .18s ${i * 0.03}s ease both`,
              }}>
              <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: "50%", flexShrink: 0,
                  background: STATUS_DOT[t.status] ?? "#c4bfb8",
                  ...(t.status === "running" ? { animation: "pulse 1.3s infinite" } : {}),
                }} />
                <span style={{
                  fontSize: 12, color: active ? "#3d352a" : "#7d7167",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  flex: 1, fontWeight: active ? 500 : 400,
                }}>
                  {t.title}
                </span>
                <button className="del-x"
                  onClick={(e) => { e.stopPropagation(); deleteTask(t.id); }}
                  style={{
                    opacity: 0, background: "none", border: "none",
                    color: "#b5a99a", cursor: "pointer", fontSize: 13,
                    padding: "0 2px", lineHeight: 1, transition: "opacity .15s",
                  }}>✕</button>
              </div>
              <div style={{ fontSize: 10, color: "#b5a99a", marginTop: 1, paddingLeft: 13 }}>
                {STATUS_LABEL[t.status] ?? t.status}
                {t.status === "done" && t.finalScore !== null && ` · ${t.finalScore.toFixed(1)}`}
              </div>
            </div>
          );
        })}
      </div>

      {/* footer */}
      <div style={{ borderTop: "0.5px solid #d4c9bb", padding: "8px 6px" }}>
        <button className="new-task-btn" onClick={() => newTask()} style={{
          width: "100%", background: "transparent", border: "none",
          display: "flex", alignItems: "center", gap: 7,
          padding: "7px 8px", borderRadius: 6,
        }}>
          <span style={{ fontSize: 14, color: "#a89a8a", lineHeight: 1 }}>＋</span>
          <span style={{ fontSize: 12, color: "#a89a8a" }}>新任務</span>
        </button>
        <button className="new-task-btn" onClick={() => setSettingsOpen(true)} style={{
          width: "100%", background: "transparent", border: "none",
          display: "flex", alignItems: "center", gap: 7,
          padding: "7px 8px", borderRadius: 6,
        }}>
          <i className="ti ti-settings" style={{ fontSize: 14, color: "#b5a99a" }} aria-hidden="true" />
          <span style={{ fontSize: 12, color: "#b5a99a" }}>Settings</span>
        </button>
      </div>
    </aside>
  );
}
