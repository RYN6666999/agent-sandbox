# 搜尋網路協議 — Search Web Protocol

> 讓 AgentOS 內外角色可以透過統一套用程式搜尋網路。
> 適用情境：需要查找文件、確認 API 用法、搜尋錯誤訊息、取得最新資訊。

---

## 角色

| 角色 | 職責 |
|------|------|
| **請求者** | 提供搜尋查詢（字串），指定結果數量 |
| **AgentOS** | 執行搜尋（透過 executor registry），回傳結構化結果 |

---

## 互動流程

```
請求者                    AgentOS
  │                         │
  │  POST /search            │
  │  {"query": "...",        │
  │   "count": 5}            │
  │────────────────────────→│
  │                         │──→ executor_registry.run("web-search", query)
  │                         │    └─ scripts/search-web.py
  │                         │       └─ orchestrator/search.search_web()
  │                         │          └─ DuckDuckGo HTML parser
  │                         │
  │  {                      │
  │   "query": "...",       │
  │   "results": [          │
  │    {"title":"...",      │
  │     "url":"...",        │
  │     "snippet":"..."}    │
  │   ],                    │
  │   "count": 5            │
  │  }                      │
  │←────────────────────────│
```

---

## API

### POST /search

```json
// Request
{"query": "python argparse example", "count": 5}

// Response
{
  "query": "python argparse example",
  "results": [
    {
      "title": "argparse — Parser for command-line options — Python docs",
      "url": "https://docs.python.org/3/library/argparse.html",
      "snippet": "The argparse module makes it easy to write user-friendly command-line interfaces."
    }
  ],
  "count": 5
}
```

### GET /search

```
GET /search?q=python+argparse&count=3
```

回傳格式同 POST。

---

## 技術實作

| 層 | 檔案 | 說明 |
|----|------|------|
| 核心 | `orchestrator/search.py` | `search_web(query, count=5)` — DuckDuckGo HTML 解析，純 stdlib |
| CLI | `scripts/search-web.py` | ArgumentParser CLI wrapper，供 executor registry subprocess 呼叫 |
| Registry | `data/settings.json` | `executors.web-search` 定義（type: subprocess） |
| API | `api/main.py` | `POST /search` + `GET /search` 端點 |
| 測試 | `tests/test_search.py` | 18 項測試（解析器 + mock HTTP + API + CLI） |

### 搜尋引擎

- **DuckDuckGo HTML 模式**（`html.duckduckgo.com`）— 伺服器端渲染，無 JavaScript
- 使用標準 `urllib` + `html.parser`（皆為 Python stdlib），零外部相依
- 15 秒逾時，結果上限 20 筆

---

## 使用範例

```bash
# 透過 shell client
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "fastapi websocket example", "count": 3}'

# GET 版本（方便快速查）
curl "http://localhost:8000/search?q=fastapi+websocket&count=3"

# 透過 executor registry
curl -X POST http://localhost:8000/executors/run \
  -H "Content-Type: application/json" \
  -d '{"name": "web-search", "args": ["fastapi websocket"]}'
```

---

## 錯誤處理

| 情境 | 回傳 |
|------|------|
| 成功 | `{query, results, count}` |
| 網路錯誤 | `{query, results:[], count:0, error:"..."}` |
| 逾時 | `{query, results:[], count:0, error:"..."}` |
| Executor 未註冊 | HTTP 500（executor_registry.run 拋 KeyError） |

---

## 紅線

- 不改 `checker.py` / `decision_log.py` / `safety.py` / `clarify.py`
- 不改 executor_registry.py 核心邏輯（只用既有 subprocess type）
- 不引入外部相依（只用 Python stdlib）
