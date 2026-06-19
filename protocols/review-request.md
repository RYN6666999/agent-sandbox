# 協議：審查請求

> **用途**：請求 Opus（或人類）審查交付成果。
> **通訊媒介**：gbrain（戰略層）或直接輸出給人類
> **時機**：功能完成、重大重構、交付前

---

## 啟動條件

Scream 在以下情況**必須**請求審查：
- [x] 新功能完成，準備交付
- [x] 重大重構完成
- [x] 架構圖或設計文件變更
- [x] 使用者要求 Opus 審查後再合併
- [x] 跨越多個 session 的大型工作完成

以下情況**不需要**審查：
- 日常 bug fix（單個小問題）
- 文件微調
- 測試補強
- Opus 已事前同意的方向

---

## 審查請求格式

### 給 Opus（透過 gbrain）

```markdown
## 交付審查請求

### 摘要
<三句話說明做了什麼>

### 功能列表
- [x] <功能 1>
- [x] <功能 2>
- [ ] <未完成的功能>

### 測試結果
- pytest：<N> passed, <M> failed, <K> skipped
- 新增測試：<N>
- 測試覆蓋變化：<before>% → <after>%

### 關鍵檔案變更
| 檔案 | 動作 | 說明 |
|---|---|---|
| path/to/file.py | 新增/修改/刪除 | 簡短說明 |

### 架構影響
<如果有架構變更，貼上更新後的架構圖或說明>

### 仍有的疑慮
1. <問題 1>
2. <問題 2>

### 請 Opus 確認
- [ ] 設計方向正確
- [ ] 實作品質可接受
- [ ] 可以交付
- [ ] 其他：<Opus 自行填寫>
```

### 給人類（直接輸出）

```markdown
## 審查請求

### 做了什麼
<一句話>

### 執行摘要
<詳細說明>

### 測試結果
pytest <N>/<M> passed

### 我認為
<Scream 自己的評估：滿意 / 有疑慮 / 建議合併>

### 請確認
- [ ] 接受 → 我將交付 / merge
- [ ] 打回 → 請說明問題
- [ ] 需要修改 → 指定要改什麼
```

---

## Opus 回覆處理

| Opus 回覆 `status` | Scream 行動 |
|---|---|
| `reviewed` | 交付 / merge，寫腦庫標記完成 |
| `rejected` | 依照 Opus 意見修正，修正後再次請求審查 |
| `clarify_needed` | 補充資訊，重新提交 |
| `approved_with_changes` | 照指定修改後直接交付，不需再審 |

---

## 審查後腦庫更新

審查完成後，Scream **必須**寫入腦庫：

```python
write_knowledge(
    key=f"project/decisions/{request_id}",
    content="審查結果摘要",
    metadata={
        "type": "review_result",
        "status": "approved" | "rejected" | "approved_with_changes",
        "reviewer": "opus" | "human",
        "reviewed_at": str,  # ISO datetime
    }
)
```