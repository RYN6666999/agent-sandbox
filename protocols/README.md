# AgentOS 協議模板庫

> 這是 agent 之間「怎麼交接、怎麼紀錄、怎麼交付」的系統提示詞庫。
> 每一份協議定義一段工作的介面合約 — 誰發起、什麼格式、怎麼驗收。

---

## 哲學

AgentOS 的核心不是智力，是**協議**。這套模板庫就是協議的具體實作。

每一份協議模板都是**一方寫給另一方的提示詞**，包含：
- **啟動條件** — 什麼時候該用這份協議
- **格式契約** — 訊息該長什麼樣子（JSON schema / markdown 模板）
- **驗收標準** — 對方怎麼知道這件事做完了
- **錯誤處理** — 對方不回、回應看不懂怎麼辦

---

## 協議一覽

| 協議 | 用途 | 路徑 |
|---|---|---|
| **Scream ↔ Opus 戰略交接** | Scream 需要 Opus 的戰略判斷、架構審查 | `handoff-opus.md` |
| **Scream → Claude Code 任務派工** | 把實作任務 deleg 給 Claude Code CLI | `delegate-claude-code.md` |
| **Scream → 小模型子代理** | 把簡單子任務下放給小模型（不寫程式） | `delegate-subagent.md` |
| **Session 紀錄** | 把 session 過程寫入腦庫 / gbrain | `record-session.md` |
| **審查請求** | 請求 Opus（或人類）審查交付成果 | `review-request.md` |
| **任務拆解** | 把大任務拆成可平行執行的子任務 | `task-breakdown.md` |
| **進度報告** | 向 gbrain / 人類報告目前進度 | `progress-report.md` |
| **經驗固化（記憶固化）** | 萃取 session 經驗為基因寫入腦庫 | `consolidate-experience.md` |
| **撰寫協議** | 寫一份新協議模板的 meta 模板 | `write-protocol.md` |

---

## 如何使用

### 從 shell 查看

```bash
# 列出所有協議
./scripts/agentos.sh protocol list

# 讀取協議內容
./scripts/agentos.sh protocol show handoff-opus

# 推送到腦庫（讓任何 agent 透過 API 讀取）
./scripts/agentos.sh protocol push handoff-opus
```

### 從 API 讀取

```bash
# 讀取已推送到腦庫的協議
curl -s 'http://localhost:8000/knowledge/protocol/handoff-opus'

# 搜尋協議內容
curl -s 'http://localhost:8000/knowledge/search?q=gbrain+交接'
```

### 從 Scream 讀取（透過知識層）

```python
from orchestrator.knowledge import read_knowledge

# 讀取協議模板
protocols = read_knowledge("protocol/handoff-opus")
```

---

## 協議撰寫原則

1. **一個協議只做一件事情** — 不要混交接、紀錄、審查在同一份
2. **格式要夠具體** — 不要寫「提供上下文」，要寫「提供哪些欄位、格式是什麼」
3. **包含錯誤路徑** — 對方不回怎麼辦、格式不對怎麼辦
4. **可測試** — 協議執行完應該有明確的完成狀態（成功 / 失敗 / 需升級）
