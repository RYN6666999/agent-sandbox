# 協議：Session 紀錄

> **用途**：把 session 過程中的重要事件寫入腦庫，供跨 session 查詢。
> **通訊媒介**：AgentOS knowledge API（`write_knowledge`）
> **時機**：session 結束時，或重大事件發生時

---

## 啟動條件

以下情況**必須**寫紀錄：
- [x] session 結束（完成 / 中止 / 交付）
- [x] 做了重要決策（選方案 / 改架構 / 設紅線）
- [x] 發現重複出現的問題模式
- [x] Opus 或人類給了指意見
- [x] 測試結果異常（大量失敗 / 新出現的 failure）

---

## 紀錄格式

```python
write_knowledge(
    key=f"session/{session_id}",      # session 層級
    content=f"# Session {session_id}\n\n## 目標\n{goal}\n\n## 做了什麼\n{what_done}\n\n## 決策\n{decisions}\n\n## 結果\n{result}",
    metadata={
        "type": "session_record",
        "status": "completed" | "interrupted" | "delivered",
        "agent": "scream" | "claude-code" | "opus",
        "project": str,
        "test_summary": {"passed": int, "failed": int, "total": int},
    }
)
```

### 重大決策紀錄

```python
write_knowledge(
    key=f"project/decisions/{request_id}",
    content=f"# 決策紀錄\n\n## 問題\n{problem}\n\n## 選項\n{options}\n\n## 選擇\n{choice}\n\n## 理由\n{reason}\n\n## 決策者\n{decider}",
    metadata={
        "type": "decision",
        "domain": "architecture" | "implementation" | "process",
        "decider": "scream" | "opus" | "user",
        "status": "implemented" | "pending" | "overturned",
    }
)
```

### 問題模式紀錄

```python
write_knowledge(
    key=f"patterns/{pattern_name}",
    content="重複出現的問題描述、根因、解決方式",
    metadata={
        "type": "pattern",
        "severity": "high" | "medium" | "low",
        "frequency": int,
        "first_seen": str,  # ISO datetime
    }
)
```

---

## 腦庫索引結構

腦庫中的 knowledge key 應該有統一的命名空間：

```
session/<session_id>           → 單次 session 完整紀錄
project/decisions/<id>         → 重大決策
project/decisions/pending/<id> → 待 Opus 確認的決策
patterns/<pattern_name>        → 重複問題模式
protocol/<protocol_name>       → 協議模板本身
```

---

## Session 結束檢查清單

Session 結束前 Scream 應確認：

- [ ] 所有重要決策已寫入 `project/decisions/`
- [ ] Session 摘要已寫入 `session/<session_id>`
- [ ] 新發現的問題模式已寫入 `patterns/`
- [ ] 測試結果已記錄（passed / failed / skipped）
- [ ] 未完成的任務已標記在 `project/backlog/`（未來功能）