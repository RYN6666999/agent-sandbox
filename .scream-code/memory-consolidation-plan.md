# 記憶固化計畫 — 讓 AgentOS 從經驗中學習

> 類比人類睡眠時的記憶固化：每次 session 結束後，自動萃取經驗教訓，寫入腦庫。

---

## 核心概念

不像人類要睡覺才能固化記憶。Scream 可以在 session 結束前（或背景任務中）主動執行一次固化：

```
Session 執行中 → 累積經驗（決策、錯誤、成功模式）
                → 固化觸發（session 結束 / 手動 / 定時）
                → 萃取基因 → 寫入腦庫
                → 下次 session 讀取 → 少踩坑
```

---

## 實作計畫

### Phase 1：手動固化（最簡單，先求有）

在 Scream Code 環境中增加一個指令或 protocol：

```
你：「固化今天的經驗」
我：掃描今天的 session context →
    萃取關鍵決策、失敗教訓、成功模式 →
    寫入腦庫 key: experience/YYYY-MM-DD/summary
```

不需要改任何 AgentOS 程式碼，純粹是 Scream 的行為規範。

### Phase 2：結構化基因格式

定義一條「基因」在腦庫中的欄位：

```json
{
  "key": "gene/planning/never-use-relative-path",
  "content": "在 AgentOS 專案中，所有路徑必須用絕對路徑，因為 subprocess 的工作目錄不固定",
  "metadata": {
    "domain": "coding",
    "source": "bug-fix",
    "date": "2026-06-20",
    "success": true,
    "tags": ["path", "subprocess", "agentos"]
  }
}
```

### Phase 3：自動固化（目標）

在 AgentOS 中新增一個固化端點，Scream 在 session 結束時自動呼叫：

```
POST /brain/consolidate
  body: {
    "session_id": "...",
    "experiences": [
      {"type": "bug", "domain": "routing", "what": "...", "fix": "..."},
      {"type": "insight", "domain": "architecture", "what": "..."},
      {"type": "decision", "domain": "model-choice", "what": "..."}
    ]
  }
  → 回傳：固化後的 gene keys
```

---

## 不做（MVP）

- 自動判斷哪些經驗值得固化（先由你手動判斷）
- 跨 session 的基因自動組合（先各自獨立）
- 基因的自我演化（未來再說）

---

## 一句話

> **每次 session 結束前花 30 秒固化經驗，比下次重新踩坑省 30 分鐘。**

---

## 待作事項

- [ ] Phase 1：寫一份「固化 protocol」進 protocols/
- [ ] Phase 2：定義 gene 格式
- [ ] Phase 3：AgentOS /brain/consolidate 端點