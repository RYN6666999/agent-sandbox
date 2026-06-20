# 協議：Skill Bridge — 自動掛載 Claude CLI Skill 到 AgentOS

> 讓 AgentOS 自動發現並註冊 Claude CLI 的 executable skill，
> Scream Code 可以直接呼叫，不用手動設定。

---

## 角色

| 角色 | 職責 |
|------|------|
| **Skill Bridge** | 掃描 `.claude/skills/`，自動註冊有腳本的 skill 為 executor |
| **AgentOS** | 執行掃描後的 executor，回傳結果給 Scream |

---

## 觸發

- **手動觸發**：`POST /skill-bridge/scan`
- **自動**（規劃中）：AgentOS 啟動時自動掃描一次

## 掃描邏輯

```
1. 遍歷 .claude/skills/{name}/
2. 檢查有無 executable 內容（優先序）：
   a. scripts/run.py → 註冊 run.py + 子命令（如 ask_question）
   b. scripts/*.py / scripts/*.sh → 直接註冊
   c. *.sh / *.py 在 skill 根目錄 → 直接註冊
3. 純知識型（只有 SKILL.md + 參考文件）→ 跳過
4. 已註冊的 skill 不重複註冊（除非 force=True）
```

## 範例

```bash
# 掃描並註冊所有 executable skill
curl -X POST http://localhost:8000/skill-bridge/scan

# 查看已註冊的 skill executors
curl http://localhost:8000/executors

# 呼叫 notebooklm 查詢
curl -X POST http://localhost:8000/executors/skill-notebooklm-ask_question/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What are the key terms in this contract?"}'

# 呼叫 military-grade 的 guard check
curl -X POST http://localhost:8000/executors/skill-military-grade-workflow-guard-check/run \
  -H "Content-Type: application/json" \
  -d '{"prompt": "check spec compliance"}'
```

## Executor 命名規則

```
skill-{name}-{subcommand}

ex: skill-notebooklm-ask_question
    skill-military-grade-workflow-guard-check
    skill-planning-with-files-init-session
```

## 檔案地圖

| 檔案 | 說明 |
|------|------|
| `orchestrator/skill_bridge.py` | 掃描器核心：掃目錄 → 解析 SKILL.md → 產生 executor defn → 註冊 + 寫入 settings.json |
| `tests/test_skill_bridge.py` | 9 項測試 |

## 紅線

- 不改 `checker.py` / `decision_log.py` / `safety.py` / `clarify.py`
- 不解析知識型 skill 的 .md 內容
- 不自動安裝依賴（每個 skill 自己管理 venv）
- 不跨機（只掃本地 `.claude/skills/`）