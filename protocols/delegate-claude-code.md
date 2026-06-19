# 協議：Scream → Claude CLI 驗收 (Checker)

> **用途**：Scream 把產出交給 Claude CLI 驗證（跑 pytest、程式碼審查）。
> **通訊媒介**：AgentOS → executor registry → Claude CLI subprocess
> **延遲特性**：同步，秒～分鐘級

---

## 角色定位

在新架構中，**Checker 是 Claude CLI**，不是 AgentOS 內部的函式：

```
Scream（Planner + Maker）
  │ 產出程式碼
  │
  ├── POST /task/verify ──→ AgentOS
  │                         ├── 有 pytest → 跑 pytest（客觀結果）
  │                         ├── 無 pytest → spawn Claude CLI 評分
  │                         └── 回傳 verdict {pass / retry / escalate}
  │
  ├── [pass]    → 交付或送審 Opus
  ├── [retry]   → 修改後再 POST /task/make
  └── [escalate] → 升級給人類
```

## 啟動條件

需要驗證產出時：
- [x] Maker 產出了程式碼 → 真跑 pytest
- [x] Maker 產出了純文字 / 無測試的程式碼 → Claude CLI 評分

**不經過** Checker 的情況：
- 純對話（/converse）
- 小雜工任務（Gemini 直接 call 不驗證）

---

## 協議步驟

```
Scream 收到 Maker 產出
  │
  ├─ 1. 審閱產出（Scream 自己看一次）
  │
  ├─ 2. POST /task/verify
  │    { "why": "...", "output": "...", "prev_score": null }
  │
  ├─ 3. AgentOS 執行：
  │     ├── 偵測是否包含 pytest
  │     ├── 有 → 寫 temp file → 跑 pytest
  │     └── 無 → spawn Claude CLI 評分
  │
  ├─ 4a. pass → Scream 交付
  ├─ 4b. retry → Scream 修改 → 再 POST /task/make
  └─ 4c. escalate → 升級給 Opus / 人類
```

---

## API 格式

### 請求

```json
POST /task/verify
{
  "why": "建立一個 CLI 工具，接受 --input 和 --output 參數",
  "output": "```python\nimport argparse\n...\n```",
  "prev_score": null,
  "max_rounds": 5
}
```

### 回應

```json
{
  "status": "pass",
  "score": 10.0,
  "feedback": "[PYTEST] 5 passed, 0 failed",
  "passed": true,
  "source": "pytest"
}
```

`status` 取值：`pass` / `retry` / `escalate`

---

## 驗收標準

- [ ] pytest path：exit code 0, failed count 0 → pass (score 10.0)
- [ ] pytest path：任何 failure → retry (score 2.0)
- [ ] pytest path：timeout → escalate (score 0.0)
- [ ] Claude CLI path：score ≥ 7.0 → pass
- [ ] Claude CLI path：score < 7.0 → retry
- [ ] Claude CLI path：error → escalate

---

## 錯誤處理

| 情況 | 處理方式 |
|---|---|
| Claude CLI 不在 PATH | escalate，告知用戶安裝 Claude Code |
| pytest timeout（>60s） | escalate，可能測試太慢 |
| Claude CLI 回傳非 JSON | 重試一次，仍失敗則 escalate |
| Checker 結果矛盾（pytest pass 但 Claude CLI 給低分） | 以 pytest 為準 |