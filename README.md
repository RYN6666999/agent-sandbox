# AgentOS — 多角色產線作業系統

> Scream 規劃與執行，Claude CLI 驗收，AgentOS 只做門禁與審計，
> Opus 當顧問（選用執行路徑），Gemini 跑雜工 — 每個人做自己擅長的事。

不是程式碼產生器，也不是聊天工具箱。五種角色協作：
**Scream（計劃+執行）**→ **Claude CLI（驗收）** 穿過 **AgentOS（安全閘道）**，
**Opus（顧問）** 只在設計階段給建議，**Gemini（雜工）** 處理廉價任務。
Maker/Checker 二元模型已升級為專業分工的產線架構。

## 四根支柱

- **真實驗收**：Checker 真的開 subprocess 跑 pytest，不接受 LLM 幻覺綠燈。
- **懂得停**：三種停損（達標 / 煞車 / 撞線），不無限燒 token。
- **危險紅線**：破壞環境的指令（rm -rf、DROP TABLE…）規則先攔，不交給模型。
- **決策可追溯**：每步分流、派工、驗收寫進 SQLite 審計日誌。

## 技術棧

FastAPI · LiteLLM · Pydantic · SQLite · MCP · Playwright  
（LangGraph 已棄用，改用 Scream 原生控制流程）  
（MVP 階段不用 Postgres / Redis / Docker / 雲端）  
（UI 評估中：React → TUI terminal UI）

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

MVP 開發中，Scream 主導計劃與執行、Claude CLI 專責驗收、AgentOS 純 Action 回圈層已上線。