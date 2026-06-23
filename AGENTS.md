# AGENTS.md — 冷啟動 agent 接駁 AgentOS 的入口

> 給任何冷啟動的 CLI agent（Scream Code / Codex / Cursor / Aider…）。
> **你是執行主體**（計劃 + 寫 code + 判斷交付）。**AgentOS 是你呼叫的基礎設施層**，
> 不是它指揮你，也不是你「操控」它。方向只有一個：你 → 呼叫 AgentOS。

## AgentOS 是什麼

「CLI 辦公室」：不寫 code、不做決策、不推理。只做四件事——
- **safety gate** — 危險指令規則先攔（rm -rf / DROP TABLE…），0 LLM。
- **真實驗收** — 真開 subprocess 跑 pytest，不接受 LLM 幻覺綠燈。
- **審計日誌** — 每步分流/派工/驗收寫進 SQLite，可追溯。
- **調度** — executor registry + 腦庫（跨 session 記憶）+ 黑板（session 內共享）+ 協議庫。

完整定位與架構見 [PROJECT.md](PROJECT.md)。

## 接上它（30 秒 runbook）

```bash
# 1. 啟後端（agent 只需要這個；要連 UI 才用 ./dev.sh）
cd ~/agent-sandbox
.venv/bin/uvicorn api.main:app --port 8000   # 或 ./dev.sh（含前端）

# 2. 確認活著
curl -s localhost:8000/health                 # {"ok":true} = 連上了
./scripts/agentos.sh health                   # 同上，client 版
```

## 怎麼呼叫（二選一，同一個後端）

**Shell client**（`scripts/agentos.sh`）：
```bash
./scripts/agentos.sh run "你的任務"            # 同步執行
./scripts/agentos.sh knowledge-write k "內容"  # 寫腦庫
./scripts/agentos.sh knowledge-read k          # 讀腦庫
./scripts/agentos.sh knowledge-search "查詢"    # 全文搜尋（中文走 LIKE fallback）
./scripts/agentos.sh protocol list             # 協議模板
./scripts/agentos.sh executors                  # 列已註冊 executor
```

**HTTP**（`AGENTOS_URL`，預設 `localhost:8000`）：
- `POST /task/make` — 一次性 maker call
- `POST /task/verify` — 真實驗收（回 pass/retry/escalate，並自動萃取 gene 存 brain）
- `GET/POST /knowledge/{key}` · `GET /knowledge/search?q=`
- `GET/POST /blackboard/{key}` — session 內共享狀態
- `POST /queue/push` · `GET /queue/status` — 背景佇列
- 端點全表見 [README.md](README.md)「API 端點一覽」。

## 你的工作流（怎麼用 AgentOS）

1. 你計劃、寫 code。**要客觀驗收 → 丟 `/task/verify`**（它真跑 pytest，不騙你）。
2. 跨 session 要記東西 → 腦庫（`knowledge-*`）。session 內傳狀態 → 黑板。
3. 背景/排程/自修復 → `/queue/push` + heartbeat daemon（見 [docs/heartbeat-daemon.md](docs/heartbeat-daemon.md)）。
4. **接手前先讀 [`.scream-code/handoff-next-session.md`](.scream-code/handoff-next-session.md)** 拿目前進度與下一棒。

## 紅線

- 勿擅改核心邏輯：`orchestrator/checker.py` / `decision_log.py` / `safety.py` / `clarify.py`。
- 不可逆動作（commit / push / 刪檔 / 改 .gitignore）一律先問人。
- 輸出繁體中文。

## 現況（一句話）

core 四循環（safety/clarify/route/verify）+ Scheduler 自修復 + Auto-Consolidate 自我成長
皆已閉環。最低可用的 maker 模型 = `qwen-2.5-7b`（更小的 1B/3B 撐不起來）。
