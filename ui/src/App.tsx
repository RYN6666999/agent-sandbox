import { useState } from "react";
import { useStore } from "./store";
import { Splash } from "./components/Splash";
import { Sidebar } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { RoundsDrawer } from "./components/CockpitView";
import { CostBar } from "./components/CostBar";
import { DiagButton } from "./components/DiagButton";
import { Settings } from "./components/Settings";

const STATUS_LABEL: Record<string, string> = {
  idle: "待命", aligning: "對齊中", running: "執行中",
  done: "完成", escalate: "需介入", error: "錯誤",
};

export default function App() {
  const { activeTask, sidebarOpen, setSidebarOpen } = useStore();
  const [showSplash, setShowSplash] = useState(true);
  const task = activeTask();

  return (
    <>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #ede8e0; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #d4c9bb; border-radius: 2px; }
        ::-webkit-scrollbar-thumb:hover { background: #c4bfb8; }
        @keyframes appIn { from{opacity:0;transform:scale(.99)} to{opacity:1;transform:scale(1)} }
      `}</style>

      {showSplash && <Splash onDone={() => setShowSplash(false)} />}

      <div style={{
        display: "flex", flexDirection: "column", height: "100vh",
        fontFamily: "system-ui, -apple-system, sans-serif",
        background: "#ede8e0",
        animation: showSplash ? undefined : "appIn 0.3s ease",
        visibility: showSplash ? "hidden" : "visible",
      }}>
        {/* top bar */}
        <div style={{
          height: 44, display: "flex", alignItems: "center",
          padding: "0 14px", gap: 10, flexShrink: 0,
          background: "#e8e1d8", borderBottom: "0.5px solid #d4c9bb",
        }}>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "#b5a99a", fontSize: 15, padding: "4px 6px", borderRadius: 5,
              transition: "color .15s",
            }}
            onMouseOver={(e) => (e.currentTarget.style.color = "#7d7167")}
            onMouseOut={(e) => (e.currentTarget.style.color = "#b5a99a")}
          >
            {sidebarOpen ? "◀" : "☰"}
          </button>
          <div style={{ width: "0.5px", height: 14, background: "#d4c9bb" }} />
          <span style={{ fontSize: 13, color: "#3d352a", flex: 1 }}>
            {task ? task.title : "AgentOS"}
          </span>
          {task && task.status !== "idle" && (
            <span style={{ fontSize: 11, color: "#a89a8a" }}>
              {STATUS_LABEL[task.status] ?? task.status}
            </span>
          )}
        </div>

        {/* body */}
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          {sidebarOpen && <Sidebar />}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <ChatView />
            <RoundsDrawer />
          </div>
        </div>

        <CostBar />
        <DiagButton />
        <Settings />
      </div>
    </>
  );
}
