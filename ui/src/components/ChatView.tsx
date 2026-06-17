import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { chatTask, approveTask, deliverTask, openWs } from "../api";
import { useStore } from "../store";

/** Merge vague original task + user's clarification into a natural sentence. */
function mergeTask(original: string, answer: string): string {
  const orig = original.trim();
  const ans = answer.trim();
  if (!ans) return orig;
  const origPrefix = orig.slice(0, 3).toLowerCase();
  if (ans.length >= orig.length && origPrefix && ans.toLowerCase().includes(origPrefix)) {
    return ans;
  }
  return `${orig} ${ans}`;
}

export function ChatView() {
  const [input, setInput] = useState("");
  const [clarifyCtx, setClarifyCtx] = useState<{ originalTask: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const { activeTask, newTask, activeTaskId } = useStore();

  // Auto-resize textarea on content change
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [input]);

  const task = activeTask();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [task?.messages]);

  function attachWs(tid: string, sessionId: string) {
    wsRef.current?.close();
    wsRef.current = openWs(sessionId, (e) => {
      const cur = () => useStore.getState().tasks.find((x) => x.id === tid)!;

      if (e.event === "status") {
        useStore.getState().updateTask(tid, { logs: [...(cur().logs ?? []), (e.data as { msg: string }).msg] });
      }
      if (e.event === "round_start") {
        const round = (e.data as { round: number }).round;
        useStore.getState().updateTask(tid, {
          messages: [...cur().messages, { role: "system" as const, text: `**Round ${round}** — 生成中…\n\n` }],
        });
      }
      if (e.event === "token") {
        const token = (e.data as { text: string }).text;
        const msgs = [...cur().messages];
        const lastIdx = msgs.length - 1;
        if (lastIdx >= 0 && msgs[lastIdx].role === "system") {
          msgs[lastIdx] = { ...msgs[lastIdx], text: msgs[lastIdx].text + token };
        } else {
          msgs.push({ role: "system", text: token });
        }
        useStore.getState().updateTask(tid, { messages: msgs });
      }
      if (e.event === "result") {
        const r = e.data as { status: string; output: string; rounds: number; final_score: number | null; history: unknown[] };
        const label = r.status === "done" ? "✓ 完成" : r.status === "escalate" ? "⚠ 需介入" : "結果";
        const scoreText = r.final_score != null ? ` · 得分 ${r.final_score.toFixed(1)} / 10` : "";
        useStore.getState().updateTask(tid, {
          output: r.output,
          history: r.history as import("../store").HistoryEntry[],
          finalScore: r.final_score,
          status: r.status as import("../store").AppStatus,
          messages: [...cur().messages, { role: "system", text: `${label}${scoreText}` }],
        });
      }
      if (e.event === "error") {
        useStore.getState().updateTask(tid, {
          status: "error",
          messages: [...cur().messages, { role: "system", text: `錯誤：${(e.data as { msg: string }).msg}` }],
        });
      }
    });
  }

  async function handleSubmit() {
    if (!input.trim()) return;
    const rawText = input.trim();
    setInput("");

    // If in clarify mode: merge original + answer, clear context, re-route
    const taskText = clarifyCtx
      ? mergeTask(clarifyCtx.originalTask, rawText)
      : rawText;
    if (clarifyCtx) setClarifyCtx(null);

    let tid = activeTaskId;
    if (!tid || useStore.getState().activeTask()?.status !== "idle") {
      tid = newTask();
    }

    const t = useStore.getState().tasks.find((x) => x.id === tid)!;
    useStore.getState().updateTask(tid, {
      title: taskText.slice(0, 28) + (taskText.length > 28 ? "…" : ""),
      messages: [...t.messages, { role: "user", text: rawText }],
      status: "running",
    });

    const res = await chatTask(taskText);

    if (res.mode === "confirm_dangerous") {
      const triggerList = (res.triggers ?? []).join("、");
      useStore.getState().updateTask(tid, {
        status: "idle",
        messages: [...useStore.getState().tasks.find((x) => x.id === tid)!.messages,
          { role: "system", text: `⚠️ 偵測到危險指令：**${triggerList}**\n\n這些操作不可逆。如果你確認要繼續，請回覆「確認繼續」。` }],
      });
      setClarifyCtx({ originalTask: taskText });
      setTimeout(() => textareaRef.current?.focus(), 50);

    } else if (res.mode === "clarify") {
      // Show clarifying question, reset to idle so user can type answer
      useStore.getState().updateTask(tid, {
        status: "idle",
        messages: [...useStore.getState().tasks.find((x) => x.id === tid)!.messages,
          { role: "system", text: res.question ?? "能說得更具體嗎？" }],
      });
      setClarifyCtx({ originalTask: taskText });
      // Restore focus to textarea
      setTimeout(() => textareaRef.current?.focus(), 50);

    } else if (res.mode === "direct") {
      useStore.getState().updateTask(tid, {
        sessionId: res.session_id,
        messages: [...useStore.getState().tasks.find((x) => x.id === tid)!.messages,
          { role: "system", text: "" }],
      });
      attachWs(tid, res.session_id);

    } else {
      // align — show questions
      useStore.getState().updateTask(tid, {
        sessionId: res.session_id,
        questions: res.questions ?? [],
        status: "aligning",
        messages: [...useStore.getState().tasks.find((x) => x.id === tid)!.messages,
          { role: "system", text: "這個任務比較複雜，對齊一下讓我更好地完成它：" }],
      });
    }
  }

  async function handleApprove() {
    const t = useStore.getState().activeTask();
    if (!t?.sessionId) return;
    const tid = t.id;

    useStore.getState().updateTask(tid, {
      messages: [...t.messages,
        { role: "user", text: "確認開工" },
        { role: "system", text: "Maker/Checker 循環啟動中…\n\n" },
      ],
      status: "running",
    });

    attachWs(tid, t.sessionId);
    await approveTask(t.sessionId, t.answers);
  }

  async function handleAccept(accepted: boolean) {
    const t = useStore.getState().activeTask();
    if (!t?.sessionId) return;
    await deliverTask(t.sessionId, accepted);
    useStore.getState().updateTask(t.id, {
      status: "idle",
      messages: [...t.messages, { role: "user", text: accepted ? "驗收通過" : "退回" }],
    });
  }

  if (!task) {
    return (
      <div style={{
        flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", background: "#ede8e0", color: "#c4bfb8", gap: 12,
      }}>
        <div style={{ fontSize: 32 }}>🧠</div>
        <div style={{ fontSize: 13, color: "#b5a99a" }}>選一個任務，或新增一個</div>
        <button onClick={() => newTask()} style={{
          background: "#3d352a", color: "#f2ede6", border: "none", borderRadius: 7,
          padding: "8px 20px", cursor: "pointer", fontSize: 12, fontWeight: 500,
        }}>＋ 新任務</button>
      </div>
    );
  }

  const { messages, status, questions, answers } = task;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", background: "#ede8e0" }}>
      <style>{`
        @keyframes msgUser  { from{opacity:0;transform:translateX(10px)} to{opacity:1;transform:translateX(0)} }
        @keyframes msgAgent { from{opacity:0;transform:translateX(-10px)} to{opacity:1;transform:translateX(0)} }
        @keyframes blink    { 0%,100%{opacity:1}50%{opacity:0} }
        .msg-u { animation: msgUser  .2s ease both; }
        .msg-a { animation: msgAgent .2s ease both; }
        .input-field { transition: border-color .15s, box-shadow .15s; outline: none; }
        .input-field:focus { border-color: #a89a8a !important; box-shadow: 0 0 0 2px #d4c9bb; }
        .q-input:focus { border-color: #a89a8a !important; box-shadow: 0 0 0 2px #e0dbd3; }
      `}</style>

      {/* messages */}
      <div style={{ flex: 1, overflowY: "auto", padding: "18px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
        {messages.map((m, i) => (
          <div key={i}
            className={m.role === "user" ? "msg-u" : "msg-a"}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "72%",
              animationDelay: `${Math.min(i * 0.03, 0.2)}s`,
            }}>
            {m.role === "system" && (
              <div style={{ fontSize: 10, color: "#c4bfb8", marginBottom: 3, paddingLeft: 2 }}>
                Agent
              </div>
            )}
            <div style={{
              background: m.role === "user" ? "#3d352a" : "#f2ede6",
              color: m.role === "user" ? "#f2ede6" : "#3d352a",
              borderRadius: m.role === "user" ? "14px 14px 3px 14px" : "14px 14px 14px 3px",
              padding: "9px 13px", fontSize: 13, lineHeight: 1.7,
              border: m.role === "system" ? "0.5px solid #d4c9bb" : "none",
            }}>
              <ReactMarkdown>{m.text}</ReactMarkdown>
            </div>
          </div>
        ))}

        {/* typing indicator */}
        {status === "running" && (
          <div className="msg-a" style={{ alignSelf: "flex-start" }}>
            <div style={{ fontSize: 10, color: "#c4bfb8", marginBottom: 3, paddingLeft: 2 }}>Agent</div>
            <div style={{
              background: "#f2ede6", border: "0.5px solid #d4c9bb",
              borderRadius: "14px 14px 14px 3px", padding: "12px 16px",
              display: "flex", gap: 5, alignItems: "center",
            }}>
              {[0, 0.16, 0.32].map((delay, i) => (
                <span key={i} style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: "#c4bfb8", display: "inline-block",
                  animation: `blink 1.1s ${delay}s ease-in-out infinite`,
                }} />
              ))}
            </div>
          </div>
        )}

        {/* alignment form */}
        {status === "aligning" && questions.length > 0 && (
          <div className="msg-a" style={{ alignSelf: "flex-start", width: "min(500px, 90%)" }}>
            <div style={{ fontSize: 10, color: "#c4bfb8", marginBottom: 3, paddingLeft: 2 }}>Agent</div>
            <div style={{
              background: "#f2ede6", border: "0.5px solid #d4c9bb",
              borderRadius: "14px 14px 14px 3px", padding: 14,
              display: "flex", flexDirection: "column", gap: 10,
            }}>
              <div style={{ fontSize: 10, color: "#b5a99a", letterSpacing: ".06em", textTransform: "uppercase" }}>
                Alignment · {questions.length} questions
              </div>
              {questions.map(({ key, q }) => (
                <div key={key}>
                  <div style={{ fontSize: 11, color: "#7d7167", marginBottom: 4 }}>{q}</div>
                  <input
                    className="q-input"
                    value={answers[key] ?? ""}
                    onChange={(e) => {
                      if (activeTaskId) useStore.getState().updateTask(activeTaskId, {
                        answers: { ...task.answers, [key]: e.target.value },
                      });
                    }}
                    style={{
                      width: "100%", background: "#ede8e0", border: "0.5px solid #d4c9bb",
                      borderRadius: 5, padding: "6px 9px", fontSize: 12,
                      color: "#3d352a", fontFamily: "inherit", outline: "none",
                      boxSizing: "border-box", transition: "border-color .15s, box-shadow .15s",
                    }}
                  />
                </div>
              ))}
              <button onClick={handleApprove} style={{
                alignSelf: "flex-start", marginTop: 2,
                background: "#3d352a", color: "#f2ede6", border: "none",
                borderRadius: 5, padding: "7px 14px", cursor: "pointer",
                fontSize: 12, fontWeight: 500,
              }}>
                確認開工
              </button>
            </div>
          </div>
        )}

        {/* accept/reject gate */}
        {(status === "done" || status === "escalate") && (
          <div className="msg-a" style={{ display: "flex", gap: 6, alignSelf: "flex-start", paddingLeft: 2 }}>
            <button onClick={() => handleAccept(true)} style={{
              background: "#eef3e8", color: "#7a8c5e", border: "0.5px solid #b5c9a0",
              borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontSize: 12, fontWeight: 500,
            }}>驗收通過</button>
            <button onClick={() => handleAccept(false)} style={{
              background: "#f5eeee", color: "#a85858", border: "0.5px solid #d4a8a8",
              borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontSize: 12, fontWeight: 500,
            }}>退回</button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* input */}
      <div style={{
        padding: "10px 14px", borderTop: "0.5px solid #d4c9bb",
        background: "#e8e1d8", display: "flex", gap: 8, alignItems: "flex-end",
      }}>
        <textarea
          ref={textareaRef}
          className="input-field"
          value={input}
          rows={1}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Cmd+Enter or Ctrl+Enter → send
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleSubmit();
              return;
            }
            // Plain Enter → newline (default textarea behaviour, do nothing)
          }}
          placeholder={status !== "idle" ? "任務執行中…" : "輸入任務… (⌘↵ 發送)"}
          disabled={status !== "idle"}
          style={{
            flex: 1, background: "#ede8e0", border: "0.5px solid #d4c9bb",
            borderRadius: 8, padding: "9px 12px", fontSize: 13, color: "#3d352a",
            fontFamily: "inherit", resize: "none", lineHeight: 1.6,
            overflowY: "auto", minHeight: 38, maxHeight: 200,
            opacity: status !== "idle" ? 0.5 : 1,
            boxSizing: "border-box",
          }}
        />
        <button
          onClick={handleSubmit}
          disabled={status !== "idle" || !input.trim()}
          title="發送 (⌘↵)"
          style={{
            width: 34, height: 34, borderRadius: 7, flexShrink: 0,
            background: (status !== "idle" || !input.trim()) ? "#d4c9bb" : "#3d352a",
            border: "none",
            cursor: (status !== "idle" || !input.trim()) ? "not-allowed" : "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14,
            color: (status !== "idle" || !input.trim()) ? "#b5a99a" : "#f2ede6",
            transition: "background .15s",
          }}
        >↑</button>
      </div>
    </div>
  );
}
