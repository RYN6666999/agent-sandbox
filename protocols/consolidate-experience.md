# 協議：經驗固化（記憶固化）

> **用途**：萃取 session 中的關鍵經驗（決策、錯誤、成功模式），寫入腦庫作為基因。
> **通訊媒介**：AgentOS knowledge API（`write_knowledge`）或 `/brain/consolidate` 端點
> **時機**：session 結束時，或累積足夠經驗後

---

## 啟動條件

以下情況**建議**執行固化：
- [x] session 結束（完成 / 中止 / 交付）
- [x] 踩到坑並找到解法（bug fix）
- [x] 做了重要架構決策
- [x] 發現重複發生的問題模式
- [x] 學到新的 workflow 技巧

---

## 基因格式（Phase 2）

每一條「基因」是腦庫中的一個 knowledge entry，key 前綴為 `gene/`：

```json
{
  "key": "gene/<domain>/<short-id>",
  "content": "經驗的具體描述，包含上下文、作法、結果",
  "metadata": {
    "domain": "coding | architecture | workflow | debugging | model-choice | tooling",
    "type": "bug-fix | decision | insight | pattern | workflow",
    "date": "2026-06-20",
    "success": true,
    "tags": ["標籤1", "標籤2"],
    "source_session": "本 session 摘要（選填）"
  }
}
```

### domain 分類

| domain | 適用場景 | 範例 key |
|--------|----------|----------|
| `coding` | 程式碼技巧、語言特性 | `gene/coding/never-use-relative-path` |
| `architecture` | 架構決策、取捨 | `gene/architecture/config-driven-over-hardcode` |
| `workflow` | 開發流程、工具使用 | `gene/workflow/always-run-pytest-before-push` |
| `debugging` | 除錯經驗、根因 | `gene/debugging/settings-silent-fail` |
| `model-choice` | 模型選擇、prompt 技巧 | `gene/model-choice/deepseek-v4-over-genspark` |
| `tooling` | CLI 工具、設定 | `gene/tooling/brave-path-for-playwright` |

---

## Phase 1：手動固化流程

當收到「固化今天的經驗」指令時：

```
1. 掃描當前 session 的關鍵事件：
   - 出了什麼 bug？怎麼修的？
   - 做了什麼決策？為什麼？
   - 學到什麼新技巧？

2. 對每個經驗：
   a. 判斷 domain + type
   b. 寫成簡潔的 gene content（包含上下文、作法、結果）
   c. 寫入腦庫 key: gene/<domain>/<short-id>

3. 回報寫入了幾條基因、key 分別是什麼
```

### 寫入方式（二選一）

**方式 A：直接寫腦庫（最簡單）**
```bash
curl -X POST http://localhost:8000/knowledge/gene/coding/never-use-relative-path \
  -H "Content-Type: application/json" \
  -d '{
    "content": "在 AgentOS 專案中...",
    "metadata": {"domain": "coding", "type": "bug-fix", ...}
  }'
```

**方式 B：透過 consolidate 端點（一次批量寫入）**
```bash
curl -X POST http://localhost:8000/brain/consolidate \
  -H "Content-Type: application/json" \
  -d '{
    "experiences": [
      {"domain": "coding", "type": "bug-fix", "what": "...", "fix": "..."}
    ]
  }'
```

---

## Phase 3：自動固化端點

`POST /brain/consolidate` 接收一或多條經驗，自動寫入腦庫並回傳 gene keys。
（見 `api/main.py` 的實作）

---

## 錯誤處理

| 狀況 | 處理方式 |
|------|----------|
| 腦庫服務離線 | 跳過固化，下次 session 再補 |
| 同一 key 已存在 | 覆蓋更新（metadata.updated_at 自動更新） |
| 經驗格式不完整 | 回傳 422，列出 missing fields |
| 批量中部分失敗 | 回傳已成功寫入的 keys + 失敗的 index |

---

## 與其他協議的關係

- **Session 紀錄** (`record-session.md`) — 紀錄「發生過什麼事件」
- **經驗固化** （本協議） — 萃取「從事件中學到了什麼」
- 兩者互補：一個記事實，一個記教訓