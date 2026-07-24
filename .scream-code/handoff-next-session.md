# Headroom 整合 — Session 交接

## 已完成

### P0 自動化（前 session）
- ✅ launchd plist → 開機自啟 + crash auto-restart
- ✅ agentos.sh 整合（headroom status|start|restart|log）
- ✅ agentos.sh up 自動確保 Headroom proxy 在線
- ✅ agentos.sh health 顯示 Headroom proxy 狀態

### P1 本 session
- ✅ **env vars → config 檔**：`~/.scream-code/headroom.toml` 建立，bridge 讀取 TOML + env var 覆蓋（`_load_headroom_config()`）
- ✅ **e2e test**：已跑 headroom pipeline 測試（mock Aris 通道、mock HTTP，覆蓋 classify→execute→compress→gate→log）

### P2 本 session
- ✅ **Kompress ML**：模型已下載（`~/.cache/huggingface/hub/models--chopratejas--kompress-v2-base/`），ONNX session 可正常載入。Proxy 的 kompress 顯示 `deferred`（非 unhealthy），第一次實際使用時自動載入。非真正問題。
- ✅ **BDD 測試**：已跑 headroom BDD 測試，參數化覆蓋 7 個 Feature 場景

## 測試狀態

- 已執行 pytest，請以「當下重跑結果」為準（避免硬編碼數字漂移）

## 剩餘工作

- P3: cron /dream（記憶整理已 7 天未跑）
- 如需正式 Kompress 啟動，可觸發一次 proxy 壓縮請求讓模型 warmup

## 關鍵檔案

| 路徑 | 說明 |
|------|------|
| `~/.scream-code/headroom.toml` | Headroom 設定檔（取代環境變數硬編碼） |
| `~/Developer/neuralis/scripts/agentos-aris-bridge.py` | bridge 本體（含 _load_headroom_config 函數） |
| neuralis headroom pipeline 測試檔（外部 repo） | e2e pipeline 測試（以 neuralis repo 為準） |
| neuralis headroom BDD 測試檔（外部 repo） | 參數化 BDD 測試（以 neuralis repo 為準） |
| `~/agent-sandbox/docs/specs/integration/headroom-bdd.md` | Headroom BDD 場景規格 |