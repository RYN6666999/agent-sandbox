import { useState } from "react";
import { useStore } from "../store";

export function DiagButton() {
  const { activeTask } = useStore();
  const [copied, setCopied] = useState(false);

  const task = activeTask();
  if (!task || task.status === "idle") return null;

  function buildReport(): string {
    if (!task) return "";
    const lines: string[] = [
      `=== AGENT SANDBOX DIAG ===`,
      `session : ${task.sessionId ?? "none"}`,
      `status  : ${task.status}`,
      `title   : ${task.title}`,
      `score   : ${task.finalScore ?? "—"}`,
      "",
    ];
    if (task.history.length) {
      lines.push("--- ROUNDS ---");
      for (const h of task.history) {
        lines.push(`Round ${h.round}  score=${h.score.toFixed(1)}  passed=${h.passed}`);
        lines.push(`  feedback: ${h.feedback}`);
      }
      lines.push("");
    }
    const errors = task.messages.filter((m) => m.text.startsWith("❌"));
    if (errors.length) {
      lines.push("--- ERRORS ---");
      errors.forEach((e) => lines.push(e.text));
      lines.push("");
    }
    if (task.logs.length) {
      lines.push("--- LOGS (last 20) ---");
      task.logs.slice(-20).forEach((l) => lines.push(l));
      lines.push("");
    }
    if (task.output) {
      lines.push("--- OUTPUT (first 300 chars) ---");
      lines.push(task.output.slice(0, 300) + (task.output.length > 300 ? "…" : ""));
    }
    return lines.join("\n");
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(buildReport());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button onClick={handleCopy} style={{
      position: "fixed", bottom: 46, right: 14, zIndex: 100,
      background: copied ? "#eef3e8" : "#f2ede6",
      color: copied ? "#7a8c5e" : "#a89a8a",
      border: `0.5px solid ${copied ? "#b5c9a0" : "#d4c9bb"}`,
      borderRadius: 7, padding: "6px 12px", cursor: "pointer",
      fontSize: 11, fontWeight: 500, display: "flex", alignItems: "center", gap: 5,
      transition: "all .15s",
    }}>
      <span>{copied ? "✓" : "🐛"}</span>
      {copied ? "已複製" : "複製診斷"}
    </button>
  );
}
