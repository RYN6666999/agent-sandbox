# 測試計劃：腦庫 SQLite 整合

> 此文件給 Claude Code 執行用。照步驟跑，不要跳。

---

## ⚠️ 已知 Bug（已修復）

Claude Code 於 2026-06-19 執行時發現並修復了兩個 bug：

1. **路由順序錯誤** — `/knowledge/{key}` 放在 `/knowledge/search` 和 `/knowledge/id/...` 前面，導致後兩條路由永遠被 wildcard 吃掉。修法：將靜態路由移到 wildcard 路由前面。
2. **路徑參數不支援斜線** — FastAPI 預設路由參數 `{key}` 無法捕捉 `/`（如 `test/cli-workflow`），且尾斜線會觸發 307 重定向導致空白回應。修法：`{key:path}` + `redirect_slashes=False`。

## 背景

AgentOS 新增了腦庫（knowledge base）模組 — SQLite + FTS5 知識儲存層。
這次測試要確認：知識模組單元測試全過、API 端點可正常回應、shell client 指令可發送。

---

## 步驟

### 1. 單元測試

```bash
cd /Users/ryan/agent-sandbox
.venv/bin/python -m pytest tests/test_knowledge.py -v
```

預期結果：**18 passed，0 failed**

### 2. 確認不影響既有測試

只跑 decision_log 測試（同是 SQLite 操作，最可能互相影響）：

```bash
cd /Users/ryan/agent-sandbox
.venv/bin/python -m pytest tests/test_decision_log.py -v --timeout=10
```

預期結果：既有測試不受影響。

### 3. 啟動 API server 做整合測試

```bash
cd /Users/ryan/agent-sandbox
.venv/bin/python -m uvicorn api.main:app --port 8000 &
sleep 2
```

### 4. HTTP API 端點測試

寫入知識：

```bash
curl -s -X POST 'http://localhost:8000/knowledge?key=test/cli-workflow' \
  -H 'Content-Type: application/json' \
  -d '{"content": "Always run pytest before commit", "metadata": {"priority": "high"}}'
```

預期：回傳 `{"ok": true, "entry_id": "<16 hex chars>"}`。存下 entry_id。

依 key 前綴查詢：

```bash
curl -s 'http://localhost:8000/knowledge/test/'
```

預期：回傳 `{"entries": [...]}`，len ≥ 1，content 包含 "Always run pytest before commit"。

全文搜尋：

```bash
curl -s 'http://localhost:8000/knowledge/search?q=pytest'
```

預期：回傳 `{"entries": [...]}`，len ≥ 1。

依 ID 查詢（替換 `<entry_id>` 為步驟 4 存下的值）：

```bash
curl -s 'http://localhost:8000/knowledge/id/<entry_id>'
```

預期：回傳單筆 dict，key = "test/cli-workflow"。

### 5. shell client 指令測試

寫入：

```bash
cd /Users/ryan/agent-sandbox/scripts
bash agentos.sh knowledge-write "test/shell-workflow" "Use Claude Code for implementation"
```

預期：回傳 `{"ok": true, "entry_id": "..."}`。

讀取：

```bash
bash agentos.sh knowledge-read "test/"
```

預期：回傳 entries，包含剛剛寫入的兩筆。

搜尋：

```bash
bash agentos.sh knowledge-search "Claude Code"
```

預期：回傳 entries，len ≥ 1。

### 6. 清理

```bash
kill %1 2>/dev/null; wait 2>/dev/null
```

---

## 驗收標準

- [ ] `test_knowledge.py` 19 項測試全過
- [ ] `test_decision_log.py` 既有測試不受影響
- [ ] HTTP POST /knowledge 回傳 entry_id
- [ ] HTTP GET /knowledge/{key} 回傳匹配 entries
- [ ] HTTP GET /knowledge/search?q=... 回傳 FTS 匹配 entries
- [ ] HTTP GET /knowledge/id/{entry_id} 回傳單筆
- [ ] shell agentos.sh knowledge-write/read/search 正常運作