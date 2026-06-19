# AgentOS — CLI 辦公室

> agent 之間自己把任務做完、並客觀驗收的流水線 — AgentOS 不寫程式、不做決策，
> 它只是辦公大樓：門禁、審計、驗收設備、排程協調。

不是程式碼產生器，也不是聊天工具箱。你丟出意圖，系統判斷 → 規劃 → 派工 →
多 agent 協作 → 自動驗收收斂 → 交付可用成果。Maker/Checker 是最小協作細胞。

## 四根支柱

- **真實驗收**：Checker 真的開 subprocess 跑 pytest，不接受 LLM 幻覺綠燈。
- **懂得停**：三種停損（達標 / 煞車 / 撞線），不無限燒 token。
- **危險紅線**：破壞環境的指令（rm -rf、DROP TABLE…）規則先攔，不交給模型。
- **決策可追溯**：每步分流、派工、驗收寫進 SQLite 審計日誌。

## 技術棧

FastAPI · LangGraph · LiteLLM · Pydantic · SQLite · MCP · React + Tauri  
（MVP 階段不用 Postgres / Redis / Docker / 雲端）

## 快速開始

**後端**

```bash
# 複製環境變數範本並填入 API key
cp .env.example .env

# 建立虛擬環境並安裝依賴（需要 Python 3.11+）
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 啟動 API server
uvicorn api.main:app --reload --port 8000
```

**前端**（Tauri + Vite，需要 Node.js 與 Rust 工具鏈）

```bash
cd ui
npm install
npm run dev        # 瀏覽器預覽（http://localhost:5173）
# 或
npm run tauri      # 原生桌面視窗
```

**測試**

```bash
pytest tests/
```

## 文件

完整願景、架構、路線圖、協作規則 → 見 [PROJECT.md](PROJECT.md)

## 狀態

MVP 開發中，核心 Maker → Checker 循環驗證階段。