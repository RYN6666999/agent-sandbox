# AgentOS Runtime — 修復計畫

## 兩輪測試發現的問題

| 優先級 | 問題 | 路由 | 類型 |
|--------|------|------|------|
| P0 | agentos.sh `up` 的 `dev.sh` 在 port 8000 被佔用時 crash | runtime | 可用性 |
| P0 | OpenCLI skills installer 陷入互動模式 | research | 自動化 |
| P1 | codebase-memory-mcp CLI stderr log 干擾 JSON 解析 | code | 工程 |
| P1 | format-validator 對 anti-hallucination 表誤報 | gate | UX |
| P2 | agentsview session data 為空（剛裝） | session | 初始化 |
| P2 | 無端到端 agent 驅動測試 | pipeline | 驗證 |

開始修。
