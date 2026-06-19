# AgentOS

> 多代理協作的超級智能體 —— 超能力是**借力**：相容萬物，調度群雄，驗收交付。

不靠自己變強，而靠**借力**：AgentOS 的能力上限不是它自己，而是它能調動的所有工具的總和。
它相容並整合各路最強的「手」（Maker、Checker、外部 agent、CLI 工具、腦庫），
把零散能力調度成一條流水線——而且借完還對結果負責驗收。它是**協調與治理層，不是執行層**：
你丟出意圖，系統判斷 → 規劃 → 派工 → 多 agent 協作 → 自動驗收收斂 → 交付可用成果。
Maker/Checker 是這個願景的最小協作細胞。

## 定調：它的職責與衡量標準

AgentOS 自己不負責「把程式寫得最強」，而負責**賦能其他模組**——讓 Maker、Checker、
外部 agent、CLI 工具、腦庫各自跑得更好。它最終只衡量一件事：

> **接上 AgentOS 的系統，解決問題的效能提升了多少。**

借力本身不稀奇，誰都能接工具；真正難、也真正值錢的，是**借力之後敢不敢信**。
這正是 AgentOS 與一般 agent 框架的根本差別：它借完一隻手，還有一套
「會驗收、會煞車、有紅線、可追溯」的治理去確保這隻手把事做對。
**相容性讓它能借力，可信治理讓借力有價值。**

由此衍生一條判準，用來決定任何新功能該不該做：

> 問：「這東西是讓 AgentOS 自己變強，還是讓接上來的模組變強？」
> 若是前者，多半是越界搶執行層的活，要警惕；若是後者，才是本分。

因此：更強的 coding 模型、CLI-Anything、OpenCLI 這類執行能力，是被 AgentOS
**調度與驗收的對象**，不是要去模仿或內化的東西。模型可換、工具可升級，
但治理職責（真驗收 / 會停 / 紅線 / 可追溯）不因換模型或換工具而動搖。

## 核心特色（治理職責的四根支柱）

- **真實驗收**：Checker 真的開 subprocess 跑 pytest，不接受 LLM 幻覺綠燈。
- **懂得停**：三種停損（達標 / 煞車 / 撞線），不無限燒 token。
- **危險紅線**：破壞環境的指令（rm -rf、DROP TABLE…）規則先攔，不交給模型判斷。
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

完整願景、架構、職責邊界、路線圖、協作規則 → 見 [PROJECT.md](PROJECT.md)

## 狀態

MVP 開發中，核心 Maker → Checker 循環驗證階段。
驗收標準不只是「循環會收斂」，而是要證明**有 AgentOS 調度 vs. 沒有**，
解決問題的效能（收斂速度 / 失敗攔截率 / 成本 / 可追溯性）確實提升。
