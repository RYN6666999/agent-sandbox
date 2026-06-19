# 協議：Scream → 小模型子代理（小雜工）

> **用途**：Scream 把簡單子任務下放給小模型（Gemini），便宜、快速、不需寫程式。
> **通訊媒介**：雙路徑 — 高價值走 AgentOS registry，低價值直接 call super-engine daemon
> **延遲特性**：同步，2～5 秒

---

## 角色定位

在新架構中，「小雜工」是 Gemini（透過 super-engine daemon），有兩條路徑：

```
高價值任務（需要追溯、可能影響決策）：
  Scream → POST /task/run (executor: "gemini")
         → AgentOS executor registry → super-engine daemon
         → 回傳結果（進 decision_log）

低價值任務（一次過、不追溯）：
  Scream → curl localhost:3456/ask (super-engine daemon)
         → 直接回傳，不走 AgentOS
```

---

## 啟動條件

**適合** deleg 給小模型的工作：
- 分類、標籤、判斷
- 小範圍搜尋與摘要
- 簡單問答、解釋
- 格式轉換（JSON → markdown 表格）
- 雙重檢查（安全風險掃描）
- 資訊提取（從 log 提取 error timestamp）

**不要** deleg 給小模型的工作：
- 需要寫程式 → 走 Maker（`/task/make`）
- 需要戰略判斷 → 走 Opus（gbrain）
- 產出需要高準確度 → Scream 自己做或多模型交叉驗證

---

## 路徑選擇原則

關鍵判斷：**這個小任務的結果會不會影響後續決策？**

| 場景 | 路徑 | 理由 |
|---|---|---|
| 分類 issue 是 bug/feature | 直接 call Gemini | 分類結果不影響下一個決策 |
| 檢查程式碼有無 SQL injection | 走 AgentOS | 結果要進決策鏈，可能影響後續動作 |
| 把 JSON 轉成表格 | 直接 call Gemini | 純格式轉換，不影響判斷 |
| 從 log 提取 error timestamp | 直接 call Gemini | 只是資料整理 |
| 驗證 error message 的 pattern | 走 AgentOS | 結果可能影響 debug 方向 |
| 摘要一份長文件 | 視情況 | 如果摘要用於決策 → 走 AgentOS |

---

## 路徑 A：走 AgentOS（審計完整）

```bash
curl -s -X POST http://localhost:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"task": "分類這段文字：...", "executor": "litellm"}'
```

優點：進 decision_log、可重試、統一回饋格式
缺點：多一跳 HTTP roundtrip

## 路徑 B：直接 call（最快）

```bash
curl -s -X POST http://localhost:3456/ask \
  -H "Content-Type: application/json" \
  -d '{"provider": "gemini", "prompt": "分類這段文字..."}'
```

優點：最快路徑、零 overhead、Scream 完全控制
缺點：不進審計、Scream 要知道 daemon 的 port

---

## 子任務提示詞模板

```markdown
你是一個專注的助理。只做一件事：

<精確描述任務>

上下文（如果有的話）：
```
<貼上相關文字>
```

輸出格式：
<明確指定：一行文字 / JSON / 條列 / 選擇題答案>

不要做：寫程式、猜測、問問題
```

### 實際範例

**分類：**
```
分類以下文字為：bug / feature / question / other

文字：載入頁面時圖片會閃爍

輸出：只輸出一個單字。
```

**提取：**
```
從以下 log 提取所有 ERROR 層級的 timestamp 和訊息：
[2025-01-01 10:00:05] ERROR connection timeout
[2025-01-01 10:00:15] ERROR db pool exhausted

輸出 JSON array：[{"time": "...", "message": "..."}, ...]
```

---

## 品質控制

| 風險等級 | 策略 |
|---|---|
| 低（分類、摘要） | 單模型一次即可 |
| 中（檢查、提取） | 兩個小模型交叉比對，不一致則 Scream 裁決 |
| 高 | 不要 deleg 給小模型 |

---

## 錯誤處理

| 情況 | 處理方式 |
|---|---|
| 模型 timeout（>5s） | 重試一次，仍失敗則 Scream 自行處理 |
| 回覆格式不對 | 補「請嚴格按照格式輸出」重試一次 |
| 內容明顯錯誤 | 自行修正或升級 |
| daemon 不在線 | fallback 走 AgentOS registry |