# Heartbeat Daemon — 讓 AgentOS 自己證明自己

自修復迴圈（inspector → runner → checker → auto-consolidate）建好了，但**沒實跑過就只是理論值**。這份 runbook 讓它實跑一段，用結果拍板：真有用，還是漂亮的空辦公室。

> ⚠️ 先決條件：偵測層在 2026-06-23 之前是 no-op（`_FAILED_LINE_RE` 配不到真實 pytest 輸出，見 `orchestrator/inspector.py` 的 commit）。實跑前先確認你的版本含該修復（`test_run_inspection_detects_real_pytest_failure` 存在且綠）。

## 一拍在做什麼

```
heartbeat 一拍：
  1. 預檢油表（今日花費 >= 上限 → 跳過，sleep 到跨日歸零）
  2. inspector：跑 pytest → 抓 FAILED → 去重 → 紅的產任務入佇列(source=A)
  3. runner：取佇列任務 → maker 修 → checker 真跑 pytest 驗 → 三停六分支
  4. 過的任務 → auto-consolidate 寫 gene 進 brain
```

## 成本模型（重要）

- **tests 全綠**：每拍只跑一次 pytest，**零 LLM、零成本**。
- **test 變紅**：runner 才 call maker（才花錢）。全局油表 `--budget`（預設 $5）撞線即停。

便宜模型 = 便宜的拍。所以實跑一天，綠的時候幾乎不花錢；它只在真的有東西壞時才動用 LLM。

## 跑之前：把 maker_model 設成安全的

預設 `data/settings.json` 的 `maker_model` 是 `web-llm-genspark`（super-engine），**無人值守會每次啟 Brave 瀏覽器**。daemon 的 preflight 會擋下並提示。改成 litellm 模型：

```json
"maker_model": "openrouter/google/gemma-4-26b-a4b-it:free"
```

需要 `.env` 有 `OPENROUTER_API_KEY`。用免費模型 = 修復也不花錢。

## 指令

```bash
scripts/heartbeat-daemon.sh start [interval_sec] [budget_usd]   # 預設 300s / $5
scripts/heartbeat-daemon.sh status      # 跑沒跑 + 佇列計數 + log 末 8 行
scripts/heartbeat-daemon.sh logs        # tail -f
scripts/heartbeat-daemon.sh stop
```

## 「證明」長什麼樣

跑一天後看 `status`：

- **佇列一直 `pending: 0` / 全綠**：沒東西可修。正常——除非你的 code 一直在改、一直有東西紅，否則自修復沒戲唱。要真正測它，故意弄紅一個測試，看下一拍它有沒有偵測→產任務→修綠。
- **`source=A` 任務 → `passed`**：✅ 它真的自己抓到、修好、記住了。loop 有用，投資回本。
- **任務一直 `escalated` / `dead`**：它抓得到但修不動，全交人。那它是個偵測器，不是修復器——價值打折，據此決定留偵測、砍修復。

## 想開機自動跑（選用，launchd）

```xml
<!-- ~/Library/LaunchAgents/com.agentos.heartbeat.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agentos.heartbeat</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>/ABS/PATH/agent-sandbox/scripts/heartbeat-daemon.sh start 300 5</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict></plist>
```

`launchctl load ~/Library/LaunchAgents/com.agentos.heartbeat.plist`

但建議先手動 `start` 觀察一兩天，確認它不亂燒錢、行為符合預期，再上 launchd。
