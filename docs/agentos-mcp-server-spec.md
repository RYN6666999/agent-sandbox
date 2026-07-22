# AgentOS MCP Server — 統合實作規劃

> **文件狀態**：v0.3（2026-07-22 修訂）
> **前身**：`hulk-nick-fury-white-tiger.md`（暫用漫威角色代號，已重命名）
> **變更摘要**：**對齊實作**。MVP 的 `sandbox_execute` 已從「任意指令執行」
> 收斂為「唯讀白名單操作」，本文件 §2 / §4.2 / §5 / §9 同步更新。

---

## 文件紀律（v0.3 新增）

**本文件以 `~/agent-sandbox/` 的實作為準。實作變更時同步改這裡，不是反過來。**

v0.2 曾與實作分歧到造成實際故障：`agentos-aris-bridge.py` 照 v0.2 §4.2 送出
`timeout` / `rollback_on_fail`，而實作端的契約沒有這兩個欄位。schema 收緊成
`additionalProperties: false` 之後，所有 shadow 呼叫開始被拒——但 bridge 用
`returncode == 0` 判定成功，於是把失敗全部記成 ok，故障靜默了一段時間。

教訓：spec 放在 `~/Downloads/` 而非版控裡，是這次漂移能長期存在的原因。
本文件現位於 `docs/`，與程式碼一起進版控。

---

## 0. 角色映射（保留原意）

早期草案用漫威角色代號描述三層分工，正式化後對應如下：


| 代號（舊）           | 系統角色（新） | 職責                        |
| --------------- | ------- | ------------------------- |
| **Hulk**        | Scream  | 執行層 — 實際跑指令、寫檔案、呼叫外部工具    |
| **Nick Fury**   | Aris    | 認知/驅動核心 — 決定「做什麼、為什麼、下一步」 |
| **White Tiger** | AgentOS | 安全/稽核層 — 沙盒、閘道、審計、拓撲管理    |


MCP Server 是 **AgentOS（White Tiger）** 的具體實作。它不決策（那是 Aris）、不執行動作邏輯（那是 Scream），只提供「安全查詢 + 安全執行」的統一介面。

---

## 1. 設計原則（三案共識）

1. **零入侵既有檔案** — `api/`、`orchestrator/`、`router/` 不改一行。MCP 層只 import，不修改。
2. **Ontology 只存可驗證的系統事實** — 不存經驗、感覺、推論。
3. **混沌 in → 秩序 out** — 輸入是模糊的意圖，輸出是結構化的工具鏈。
4. **MCP Server 獨立程序** — 與 FastAPI (port 8000) 並存於 port 8001。
5. **拉式優先** — Loop 循環由客戶端主動呼叫觸發；不引入背景 thread。理由見 §6。

---

## 2. 檔案結構

> **v0.3 更正**：實際落地的目錄是 **`mcp_server/`**，不是下表原本寫的 `mcp/`。
> 下方結構已改為實際路徑。`sandbox/` 底下另有 v0.2 未預期的 `workspace.py`
> （持久 root_fd + workspace identity 驗證），是 fd-relative 安全模型的核心。

```
~/agent-sandbox/
├── agentos.json              ← 既有，僅存 config/schema；ontology 事實入 SQLite
├── mcp_server/               ← 新增：MCP 層（平行於 api/）
│   ├── __init__.py
│   ├── server.py             ← FastMCP 入口，註冊所有 tools
│   ├── config.py             ← 設定載入（agentos.json + env）
│   │
│   ├── ontology/             ← 系統拓撲引擎（What）— v0.2 交付
│   │   ├── __init__.py
│   │   ├── model.py          ← 資料結構：Tool, Route, Dependency, Snapshot
│   │   ├── store.py          ← 持久化（SQLite，只存系統事實）
│   │   ├── scanner.py        ← 本機工具掃描（版本、能力、路徑）
│   │   └── health.py         ← 健康檢查（ping/process/file 三種模式）
│   │
│   ├── sandbox/              ← 沙盒執行（How 的代理層）— MVP 交付
│   │   ├── __init__.py
│   │   ├── workspace.py      ← 【v0.3 新增】持久 root_fd + identity 驗證
│   │   ├── checkpoint.py     ← 檔案快照（SHA256 + tar.gz）※ 目前 execute 觸達不到
│   │   ├── executor.py       ← 白名單唯讀操作（fd-relative，非 subprocess）
│   │   └── rollback.py       ← 失敗自動/手動恢復 ※ 目前 execute 觸達不到
│   │
│   ├── gate/                 ← 安全閘道 — MVP 交付
│   │   ├── __init__.py
│   │   ├── rules.py          ← 危險指令規則（port from safety.py）
│   │   └── audit.py          ← 審計日誌寫入（JSONL）
│   │
│   ├── loop/                 ← Observe → Detect → Validate → Act（純拉式）— v0.3 交付
│   │   ├── __init__.py
│   │   ├── observer.py       ← 被動掃描：僅在 loop_observe 被呼叫時執行
│   │   ├── detector.py       ← 比對 ontology 與實際狀態
│   │   ├── validator.py      ← 一致性檢查（路由完整性、版本漂移）
│   │   └── actuator.py       ← 修復/通知（啟動 down 工具、更新路由）
│   │
│   ├── knowledge/            ← 統一記憶查詢入口 — v0.2 交付
│   │   ├── __init__.py
│   │   ├── router.py         ← dispatch 到後端
│   │   └── backends/
│   │       ├── gbrain.py     ← HTTP client
│   │       ├── memory.py     ← scream-code MemoryLookup API
│   │       └── qmd.py        ← qmd CLI wrapper
│   │
│   └── tests/                ← 測試，與模組對應
│       ├── test_sandbox.py   ← MVP 交付
│       ├── test_gate.py      ← MVP 交付
│       ├── test_ontology.py
│       ├── test_loop.py
│       └── test_knowledge.py
│
├── api/main.py               ← 不變
├── orchestrator/             ← 不變，loop 模組 import 其決策日誌
└── scripts/agentos.sh        ← 加 `mcp` 子命令
```

**目錄命名決策**：~~`mcp/`（Plan 2 的簡潔名稱）而非 `mcp_server/`~~
**（v0.3 作廢，實作採用 `mcp_server/`）**

v0.2 的決定在這個 codebase 上行不通，與簡潔與否無關：專案本地的 `mcp/`
會**遮蔽官方 PyPI 套件 `mcp`**。`server.py` 開頭有
`sys.path.insert(0, repo_root)`，repo 根目錄排在 site-packages 之前，因此
`from mcp.server.fastmcp import FastMCP` 會解析到本地目錄而不是 SDK。

實測：在含空 `mcp/` 套件的目錄下 import，得到
`ModuleNotFoundError: No module named 'mcp.server'`。

---

## 3. Ontology Engine 資料結構

### 3.1 核心實體（model.py）

```python
@dataclass
class Tool:
    id: str                          # 'codebase-memory-mcp'
    name: str                        # 人類可讀名稱
    kind: Literal["mcp","cli","skill","service","pipeline"]
    version: str                     # semver
    status: Literal["active","degraded","unavailable","unknown"]
    capabilities: list[str]          # ['code-graph','search','architecture']
    dependencies: list[str]          # 工具 ID 列表
    path: str | None                 # 安裝路徑
    health_check: HealthCheckConfig  # 健康檢查設定
    metadata: dict                   # 延伸資訊

@dataclass
class Route:
    id: str                          # 'code', 'research'
    tool_chain: list[str]            # 工具 ID 有序鏈
    priority: int                    # 0=最高
    is_active: bool
    fallback: str | None             # 備援路由 ID

@dataclass
class Dependency:
    tool_id: str
    depends_on: str
    constraint: str                  # '>=1.0.0', 'exact', 'any'
    optional: bool

@dataclass
class SystemSnapshot:
    timestamp: str                   # ISO 8601
    tools: list[Tool]
    routes: list[Route]
    health_summary: dict
```

### 3.2 agentos.json 定位收斂（單一事實來源紀律）

**決策**：`agentos.json` **只放 config/schema/期望狀態**，ontology 觀測事實**只進 SQLite**。`ontology_refresh` 不寫回 json。

**兩份事實的角色**：


| 儲存體                    | 角色               | 誰寫                         |
| ---------------------- | ---------------- | -------------------------- |
| `agentos.json`         | 宣告的期望狀態（DESIRED） | 人手寫 / 版本控管                 |
| `ontology.db` (SQLite) | 實際觀測狀態（ACTUAL）   | `scanner.py` / `health.py` |


`ontology_diff` 專門拿來比 DESIRED vs ACTUAL — 漂移偵測不再是副作用，是主功能。

```json
{
  "version": "0.4.0",
  "ontology": {
    "schema_version": "1.0.0",
    "desired_tools": {
      "codebase-memory-mcp": {
        "version": ">=0.8.0",
        "kind": "mcp",
        "capabilities": ["code-graph","search","architecture","trace"],
        "dependencies": [],
        "health_check": {"type": "process", "name": "codebase-memory-mcp"}
      },
      "agentos-aris-bridge": {
        "version": "0.1.0",
        "kind": "service",
        "capabilities": ["aris-bridge"],
        "dependencies": ["aris-channel"],
        "health_check": {"type": "file", "path": "/tmp/aris-scream-channel.jsonl"}
      }
    },
    "relationships": [
      {"from": "agentos-aris-bridge", "to": "aris-channel", "type": "depends-on"},
      {"from": "codebase-memory-mcp", "to": "python3", "type": "depends-on", "optional": true}
    ],
    "pipeline_stages": ["input","context","execute","gate","log"]
  }
}
```

### 3.3 持久化（store.py — SQLite）

```sql
CREATE TABLE IF NOT EXISTS ontology_tools (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    capabilities TEXT NOT NULL DEFAULT '[]',
    dependencies TEXT NOT NULL DEFAULT '[]',
    path TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ontology_snapshots (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    trigger TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ontology_health_history (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    checked_at TEXT NOT NULL
);
```

### 3.4 不變量

1. **Ontology 是唯讀快照** — 只在 `refresh`/`snapshot` 時寫入 SQLite，MCP tools 唯讀
2. **健康狀態 60s 過期** — 未更新標記 `degraded`
3. **路由不能懸空** — 所有 `Route.tool_chain` 必須指向存在的 `Tool.id`，否則標記 `broken`
4. **版本漂移檢測** — SQLite 實測版本 vs `agentos.json` desired 版本不一致時標記 `drift_detected`
5. **工具消失不刪條目** — `status` 設 `unavailable`，保留歷史
6. **`agentos.json` 唯讀於運行時** — 任何 MCP tool 不得寫回 json

---

## 4. MCP Tools 清單（v1.0 全景，共 10 個工具）

> MVP 只做其中 1 個（`sandbox_execute`），其餘依 §9 分階段交付。
> 所有工具透過 `FastMCP` 註冊在 `server.py` 中，port 8001。

### 4.1 Ontology（4 tools） — v0.2


| Tool                | 參數                                                                          | 行為                                          | 安全            |
| ------------------- | --------------------------------------------------------------------------- | ------------------------------------------- | ------------- |
| `ontology_query`    | `query_type: enum(topology|tool|dependents|health|pipeline)`, `query?: str` | 統一查詢入口。回傳對應的拓撲子集                            | 唯讀            |
| `ontology_snapshot` | `trigger: str = "manual"`                                                   | 建立當前系統拓撲快照 + 寫入 SQLite                      | 唯讀            |
| `ontology_diff`     | `snapshot_a: str, snapshot_b: str`                                          | 比對兩個快照的差異（工具/版本/狀態）；亦支援 `desired vs actual` | 唯讀            |
| `ontology_refresh`  | `{}`                                                                        | 重新掃描本機工具，更新 SQLite（**不寫回 agentos.json**）    | 需寫入 SQLite 權限 |


### 4.2 Sandbox（3 tools） — `sandbox_execute` 屬 MVP，其餘 v0.2


| Tool                 | 參數                                                    | 行為                                                                                              |
| -------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `sandbox_execute`    | `operation: str, path: str = "", session_id: str = "default"` | **唯讀白名單操作**。回傳 `{status, stdout, stderr, checkpoint_id, rollback_applied}` |
| `sandbox_checkpoint` | `session_id: str, label?: str`                        | 主動建立 checkpoint。回傳 `{checkpoint_id, state_hash}`                                                |
| `sandbox_rollback`   | `checkpoint_id: str`                                  | 手動回退到指定 checkpoint。回傳 `{status, restored_files}`                                                |


#### `sandbox_execute` 契約（v0.3 對齊實作，取代 v0.2 的 command API）

```json
{"operation": "get_cwd", "path": "", "session_id": "default"}
```

- `operation` 限白名單三選一：`list_directory` / `read_file` / `get_cwd`
- `path` 為 workspace 相對路徑，型別是 `str`（**不接受 `null`**），`get_cwd` 傳 `""`
- inputSchema 是 `additionalProperties: false`，**多送任何欄位一律被拒**
- 沒有 `command`、沒有 `timeout`、沒有 `rollback_on_fail`

**為什麼從 `command` 改成 `operation`**：任意指令執行與目前的安全模型
（fd-relative open + `O_NOFOLLOW` + workspace identity 驗證）衝突。白名單化之後，
路徑逃逸、symlink 攻擊、option injection、shell metachar 都在契約層就擋掉，
不必倚賴指令字串的過濾。這是刻意的收窄，不是尚未實作。

**呼叫端注意**：tool 回 `isError` 時 MCP server 仍是正常結束（exit 0）。
**不可用 process returncode 判定呼叫成功**，必須解析回應的 `isError`。

**關鍵設計**：sandbox 只管理檔案狀態（file hash + tar.gz），不管理程序狀態。AgentOS 是管家不是執行層。

**現況限制**：白名單三個操作都是唯讀，因此 `sandbox_execute` 路徑上
**不會產生 checkpoint**，回傳的 `checkpoint_id` 恆為 `null`、`rollback_applied`
恆為 `false`。`checkpoint.py` / `rollback.py` 模組已實作且有測試覆蓋，但目前
**無法經由 `sandbox_execute` 觸達**。要啟用需先引入會修改檔案的操作。

### 4.3 Loop（2 tools） — v0.3


| Tool           | 參數                        | 行為                                                                                                 |
| -------------- | ------------------------- | -------------------------------------------------------------------------------------------------- |
| `loop_observe` | `{}`                      | **拉式**觸發。觀察系統狀態：工具健康、queue depth、budget、pending tasks。回傳 `{timestamp, tools, queue_depth, budget}` |
| `loop_act`     | `mode: enum(report|auto)` | `report`=回報異常；`auto`=嘗試修復（啟動 down 工具、更新路由）                                                         |


### 4.4 Knowledge（1 tool） — v0.2


| Tool              | 參數                                                                       | 行為                                                                                                   |
| ----------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `knowledge_query` | `query: str, sources: list[str]=["local","gbrain","qmd"], limit: int=10` | 統一記憶查詢。依 `sources` 決定後端，合併回傳 `[{source, id, key, content, score}]`。任一後端不可用時回傳 `{source, error}` 而非拋錯 |


**不提供 `knowledge_write`** — 違反「AgentOS 只存系統事實」原則；寫入記憶是 Aris/Scream 的職責。

---

## 5. Sandbox 實作方式

### 演算法

```
checkpoint(session_id):
  1. 掃描 cwd（或指定 path），記錄所有檔案 SHA256 hash
  2. 壓縮 snapshot 到 snapshots/{session_id}/{ts}.tar.gz
  3. 記錄受保護的環境變數
  4. 回傳 checkpoint_id (UUID)

執行流程（v0.3 對齊實作，取代 v0.2 的 subprocess 版本）:

execute(operation, path, session_id):
  1. if operation not in ALLOWED_OPS: return {status: "blocked"}
  2. 驗證 path：非絕對路徑、非 "-" 開頭、無 shell metachar、分割成 parts
  3. dup_root_fd = workspace.dup_fd()        # 含 workspace identity 驗證
  4. 以 fd-relative + O_NOFOLLOW 逐段開啟，執行唯讀操作
  5. 寫 audit log，return {status, stdout, stderr,
                           checkpoint_id: null, rollback_applied: false}

  ※ 唯讀，不建 checkpoint、不會 rollback。步驟 1-3 任一失敗即 blocked。
  ※ 沒有 subprocess，沒有 timeout 參數 — 不執行外部指令。

rollback(checkpoint_id):
  1. 讀取 snapshot JSON
  2. 對比當前檔案 hash → 只看有變更的檔案
  3. 從 snapshot tar.gz 解壓縮還原
  4. 清除 checkpoint 記錄
```

### 邊界案例

- **磁碟空間不足**：snapshot 失敗 → 記錄 warning，不回退，回傳 `checkpoint_failed: true`
- **並發 checkpoint**：各自獨立檔案，不共享鎖
- **目標目錄已刪除**：從 tar.gz 重建
- **checkpoint TTL**：24h，逾期自動清除

---

## 6. Loop 模式決策 — 純拉式（PULL-ONLY）

### 決策

**MVP + v1.0 全採拉式。** MCP Server 不內建背景 thread、不定時 tick、不主動掃描。所有循環觸發都必須來自客戶端（Aris / Scream）呼叫 `loop_observe` 或 `loop_act`。

### 為什麼不推式（依你的信條逐條對映）


| 你的原則                 | 推式的違反                                     |
| -------------------- | ----------------------------------------- |
| **Level 1 結構安全優先**   | 背景 thread = 引入不可預測執行點                     |
| **Adversarial 評估**   | 拉式狀態可重現、可測試；推式的觀察狀態受背景 tick 時序影響，難以做對抗性測試 |
| **Fixed budget**     | 推式吃常駐 CPU / 記憶體，MVP 就把預算漏光                |
| **Private/Held-out** | 拉式的每次觀察都是明確 request；推式的觀察隱藏在背景，難稽核        |


### 何時可以加推式（未來延伸，非 v1.0 範圍）

僅當出現以下明確 SLA 需求：

- 「工具掛掉必須在 N 秒內偵測並自動修復」
- 「budget 耗盡必須自動終止 pipeline」

屆時新增 `mcp/scheduler/`（獨立子系統），且必須：

1. 可透過 config 完全關閉
2. 每次背景 tick 也走 audit log
3. 明文標記為「Level 2 特性」，預設關閉

---

## 7. Knowledge Router 設計

### 統一查詢介面

```python
# knowledge/router.py

BACKENDS = {
    "local": MemoryBackend(),      # scream-code MemoryLookup
    "gbrain": GBrainBackend(),     # Aris gbrain HTTP API
    "qmd": QmdBackend(),           # qmd CLI
}

async def query(query: str, sources: list[str], limit: int) -> list[dict]:
    """平行查詢多個後端，合併結果"""
    results = []
    for source in sources:
        backend = BACKENDS.get(source)
        if not backend:
            continue
        try:
            results.extend(await backend.search(query, limit))
        except Exception as e:
            results.append({"source": source, "error": str(e)})
    # 依 score 排序（score 高的優先），取前 limit
    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return results[:limit]
```

### 後端介面

```python
@dataclass
class KnowledgeEntry:
    source: str
    id: str
    key: str
    content: str
    metadata: dict
    score: float
    created_at: str

class KnowledgeBackend(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int) -> list[KnowledgeEntry]: ...
    @abstractmethod
    async def check_health(self) -> bool: ...
```

**AgentOS 不提供 write** — 寫入記憶是 Aris/Scream 的職責。

---

## 8. 與現有系統的遷移路徑

### Phase 1：共存（不修改現有 bridge）

```
現狀：agentos-aris-bridge.py (5-stage pipeline) ← 直接服務 Aris
目標：agentos-aris-bridge.py → MCP Server → 服務所有 MCP 客戶端

遷移步驟：
1. 新增 mcp/ 目錄，實作 MCP Server（port 8001）
2. agentos-aris-bridge.py 的 execute 階段改為呼叫 MCP tools
   ─ 而非直接呼叫 Scream 工具
3. 舊 bridge 保留為「Aris 專用通道」，MCP Server 為通用層
4. 逐步 deprecate 舊 bridge 的自有邏輯，全部路由到 MCP Server
```

### 具體 migration 路徑


| 步驟  | 變更                                                  | 影響                            |
| --- | --------------------------------------------------- | ----------------------------- |
| 1   | 實作 `mcp/` 全部模組                                      | 無（新目錄）                        |
| 2   | `agentos.sh mcp start` → launch MCP Server          | 無（新子命令）                       |
| 3   | `agentos-aris-bridge.py` 的 execute 階段 call MCP tool | 向下相容                          |
| 4   | 舊 FastAPI 端點 (port 8000) 逐步 deprecate               | 需通知 Scream/Cline 改用 port 8001 |


---

## 9. MVP 範圍（8020 收斂版）

### MVP 交付：**只做 `sandbox_execute` 一個工具**

**為什麼是它 — 一個工具驗證六個子系統**：


| 子系統        | `sandbox_execute` 一路跑通能證明什麼 |
| ---------- | --------------------------- |
| MCP 協議     | 客戶端能連 port 8001 並呼叫工具       |
| Gate       | 危險指令被擋（`rm -rf /` 級）        |
| Checkpoint | 執行前有 SHA256 + tar.gz        |
| Rollback   | 執行失敗會自動還原檔案                 |
| Audit log  | JSONL 有留紀錄                  |
| Config     | `agentos.json` 正確載入         |


其餘工具（`ontology_*` / `knowledge_query` / `loop_*` / `sandbox_checkpoint` / `sandbox_rollback`）**全部延到 v0.2 之後**。理由：

- `ontology_query` 只讀，跑通只證明「MCP 協議活著」，槓桿低
- `knowledge_query` 依賴 3 個外部後端，任一掛掉卡 MVP，不驗證安全機制
- `ontology_refresh` 是寫入路徑但沒 sandbox 保護，反而是危險路徑

### MVP 實作範圍（7 個檔案）

```
mcp_server/                  # 實際路徑（非 v0.2 寫的 mcp/）
├── server.py                # FastMCP 骨架 + arg model 收緊（extra=forbid）
├── config.py                # 讀 agentos.json；AGENTOS_WORK_DIR 必須顯式設定
├── gate/
│   ├── rules.py             # ALLOWED_OPS 白名單（與 executor 一致，有測試斷言）
│   └── audit.py             # JSONL 寫入
├── sandbox/
│   ├── workspace.py         # 持久 root_fd + identity 驗證
│   ├── executor.py          # fd-relative 唯讀操作
│   ├── checkpoint.py        # 已實作，execute 路徑觸達不到
│   └── rollback.py          # 已實作，execute 路徑觸達不到
└── tests/
    └── test_sandbox_execute.py   # 34 cases（含 TOCTOU 壓力測試）
```

### MVP 驗收標準（v0.3 改寫，對齊唯讀白名單設計）

v0.2 的三條有一條在目前設計下**測不了**：第 2 條要求「跑一個會刪檔案的錯誤
指令後檔案被自動還原」，但白名單沒有任何會寫檔的操作，也沒有任意指令執行。
不是還沒做，是刻意不做。改為：

1. **正常路徑**：`sandbox_execute {"operation":"list_directory"}` 回傳目錄內容
2. **契約攔截**：未知 operation（如 `rm`）回 `status: "blocked"`；
   未知參數（如 `bogus_param`）回 `isError: true`，且 `tools/list` 的
   inputSchema 帶 `additionalProperties: false`
3. **路徑攔截**：絕對路徑、`../` 逃逸、symlink、`-` 開頭、shell metachar
   全部回 `blocked`，audit log 有紀錄

**延後到「有寫入操作」時才驗收**（模組已實作且單獨測過，但 execute 觸達不到）：

- checkpoint 自動建立
- 失敗自動 rollback

三條過了 = 契約層與路徑層的安全模型立住。**但要注意這證明的是
「唯讀沙盒安全」，不是「可回退的執行沙盒安全」**——後者尚未被端到端驗證。

### 後續版本規劃


| 版本             | 新增內容                                                                 | 交付價值         |
| -------------- | -------------------------------------------------------------------- | ------------ |
| **v0.1 (MVP)** | `sandbox_execute` + gate + checkpoint/rollback + audit               | 安全執行骨幹       |
| **v0.2**       | ontology (4 tools) + knowledge\_query + sandbox\_checkpoint/rollback | 系統可視性 + 記憶查詢 |
| **v0.3**       | loop\_observe + loop\_act（純拉式）                                       | 主動偵測與修復      |
| **v0.4+**      | 依實際 SLA 需求決定是否加背景 tick（Level 2 特性）                                   | —            |


---

## 附錄 A：變更紀錄


| 日期         | 變更                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------- |
| 2026-07-20 | v0.1 初稿（三案共識整合，暫名 `hulk-nick-fury-white-tiger.md`）                                          |
| 2026-07-21 | v0.2 修訂：檔名正式化、角色映射入文、Loop 定案拉式、`agentos.json` 收斂為 config-only、MVP 收斂至 `sandbox_execute` 單工具 |
| 2026-07-22 | v0.3 **對齊實作**：文件移入 `docs/` 納版控；目錄更正為 `mcp_server/`（附遮蔽 SDK 的實測理由）；§4.2 `sandbox_execute` 改為唯讀白名單契約（`operation`/`path`/`session_id`，`additionalProperties:false`）；§5 演算法改為 fd-relative 唯讀流程；§9 驗收標準改寫，明列 checkpoint/rollback 目前觸達不到；加註「不可用 returncode 判定呼叫成功」 |


&nbsp;