# 協議：Scream ↔ Opus 戰略交接 (gbrain)

> **用途**：Scream 需要 Opus 的戰略判斷、架構審查、重大決策時使用。
> **通訊媒介**：gbrain（會議記錄 — Postgres + R2）
> **延遲特性**：非同步，分鐘～小時級

---

## 啟動條件

Scream 在以下情況**必須**啟動此協議：
1. 架構方案有兩個以上選擇，需要判斷方向
2. 交付前最終審查 — Opus 點頭才算過
3. 專案路線偏移，需要重新確認戰略
4. 使用者明確要求 Opus 介入

日常迭代（pytest 有過、低風險）Scream 自行決定，不需走此協議。

---

## 協議步驟

```
Scream 判斷需要 Opus
  │
  ├─ 1. 寫 gbrain（格式見下方）
  │    session: "專案_YYYYMMDD"
  │    from: "scream"
  │    to: "opus"
  │    type: "strategic_direction" | "deliverable_review" | "course_correction"
  │    status: "awaiting_reply"
  │
  ├─ 2. 寫腦庫（同步知識）
  │    write_knowledge("project/decisions/pending/<request_id>", ...)
  │
  ├─ 3. 等待 Opus 回覆
  │    繼續做其他工作，不 blocking
  │
  ├─ 4. 讀到 Opus 回覆
  │    status: "reviewed" | "rejected"
  │    content: Opus 的意見
  │
  ├─ 5a. [reviewed] → 照 Opus 方向繼續執行
  ├─ 5b. [rejected] → 修正後再次提交
  └─ 5c. [clarify]  → 補充資訊後再次提交
```

---

## gbrain 訊息格式

### 請求戰略方向

```json
{
  "session": "專案_20260619",
  "from": "scream",
  "to": "opus",
  "type": "strategic_direction",
  "content": "問題描述：\n- 背景：...\n- 兩個方案：\n  A) ...\n  B) ...\n- 我的傾向：A，因為...\n- 卡住的地方：...",
  "status": "awaiting_reply"
}
```

### 請求交付審查

```json
{
  "session": "專案_20260619",
  "from": "scream",
  "to": "opus",
  "type": "deliverable_review",
  "content": "交付摘要：\n- 功能：...\n- 測試結果：18/18 passed\n- 關鍵檔案：...\n- 架構圖已更新在：...\n- 仍有的疑慮：...",
  "status": "awaiting_approval"
}
```

### 請求路線修正

```json
{
  "session": "專案_20260619",
  "from": "scream",
  "to": "opus",
  "type": "course_correction",
  "content": "目前狀況：\n- 原本計劃：...\n- 實際進度：...\n- 偏離原因：...\n- 建議調整：...\n- 需要 Opus 確認：...",
  "status": "awaiting_reply"
}
```

---

## Opus 回覆格式

```json
{
  "session": "專案_20260619",
  "from": "opus",
  "to": "scream",
  "type": "strategic_direction",
  "content": "判斷：選方案 A\n理由：...\n注意事項：\n1. ...\n2. ...\n邊界條件：...",
  "status": "reviewed"
}
```

`status` 可以是：
- `reviewed` — 批准，照做
- `rejected` — 打回，需修正
- `clarify_needed` — 資訊不足，請補充

---

## 腦庫同步

每次 gbrain 交接後，Scream 應同步寫入腦庫：

```python
write_knowledge(
    key=f"project/decisions/{request_id}",
    content=f"決策：{decision_summary}",
    metadata={
        "from": "scream" | "opus",
        "type": str,
        "status": str,
        "gbrain_session": str,
    }
)
```

---

## 錯誤處理

| 情況 | 處理方式 |
|---|---|
| Opus 超過 24h 未回 | 發 reminder 到 gbrain（status: "reminder"） |
| Opus 回覆格式不對 | 試著解析，無法解析則標記為需人工檢視 |
| Opus 拒答（status: "cannot_answer"） | 升級給使用者 |
| gbrain 寫入失敗 | 不阻斷流程，先繼續執行，下次再試 |
