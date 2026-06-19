# 決策日誌 (Decision Log)

> 本文件記錄專案關鍵決策的「為什麼」與「否決了什麼」，不是進度清單（進度見 PROJECT.md）。
> 接手的大腦/策略角請先讀完本文件，避免重提已被否決的方向。
> 格式：決策 → 為什麼 → 否決了什麼 / 邊界 → 可被推翻的條件。

---

## D1. Checker 必須真跑 pytest，不接受 LLM 評分當綠燈
- **決策**：Checker 偵測到含測試的程式碼 → 開 subprocess 真跑 pytest，用真實 pass/fail 當分數；只有非程式碼/無測試任務才 fallback LLM 評分（標記 LLM_SCORED）。
- **為什麼**：`.sdd/` 裡發現大量 78 bytes、內容相同的假綠燈 JSON。LLM 只看文字打分，程式碼跑不起來也能過，整個 Maker/Checker 循環建立在假驗收上。
- **否決 / 邊界**：不接受「LLM 自評」作為程式碼任務的驗收依據。失敗一律壓分到 <7.0，score 永不覆蓋 pytest 判決。
- **可推翻條件**：除非有比 pytest 更客觀的驗證手段，否則此決策不動。

## D2. score 與 passed 分離
- **決策**：passed 只看 pytest 結果（exit_code==0 且 failed_count==0）；score 只供 loop.py 的 no_progress 計算。過=10 / 敗=2 / 逾時或語法錯=0。
- **為什麼**：避免分數換算邏輯反過來覆蓋真實的測試判決，製造另一種假綠燈。
- **邊界**：任何 pytest 失敗都強制 score <7.0，不可因換算邏輯讓它溜過。

## D3. 危險指令用規則攔，不交給模型；只擋炸環境的，不擋業務邏輯
- **決策**：safety.py 純規則零 LLM，攔截不可逆、大範圍破壞執行環境的指令（rm -rf、DROP TABLE、push --force、格式化…）。業務級刪除（如「刪除重複資料」）放行。DELETE FROM 還會檢查有無 WHERE。
- **為什麼**：規則可復現、成本零、可審計；模型判斷是機率性的，不該拿來守紅線。
- **否決 / 邊界**：不擋 `git push`（不帶 force）、不擋業務語意的刪改。曾誤殺 `DELETE FROM ... WHERE` 已修正。
- **位置**：safety gate 已移到 clarify 之前（否則危險輸入會先被當模糊輸入追問）。

## D4. 模糊輸入「寧可多問」，但任務 vs 閒聊必須先分類
- **決策**：過短/模糊輸入先反問一句（clarify gate）。但閒聊類輸入（如「你好」「你是誰」）走 /converse 直接回答，不進任務流程。
- **為什麼**：一開始只有「清晰/模糊/複雜」三條路，沒有「這不是任務」的路徑，導致「你好」被當模糊任務，陷入無限追問死循環。
- **否決 / 邊界**：不是模型不夠聰明的問題，是流程缺了分類路徑。換更強模型也救不了缺口。
- **後續方向**：預設聊天，使用者明確按「執行任務」才進任務流程（設計中）。

## D5. 不借 Cherry Studio 的核心，最多當前端殼
- **決策**：不把 Cherry 的程式碼搬進專案。若要借，只當 UI 殼（透過 OpenAI 相容端點把 AgentOS 掛成一個 model）。
- **為什麼**：Cherry 停在單 agent 階段（GitHub issue #13301 多 agent 還在 wishlist），提供不了我們要的多 agent 協作引擎。技術棧也不同（Cherry 是 Electron，我們是 FastAPI + React/Tauri），搬程式碼是維護惡夢。
- **否決**：否決「直接複製 Cherry 程式碼」。我們的護城河是 Maker/Checker 真實驗收循環，那是 Cherry 沒有的。
- **可推翻條件**：核心引擎驗證完後，若自建 UI 成本過高，可評估用 Cherry 當純前端殼。

## D6. 模型分層，Agnes 只跑雜活不放主控
- **決策**：策略/架構判斷用最強模型（Opus 4.8）；執行寫程式用中階（Sonnet 4.6）；閒聊/Checker 整理回饋等雜活用便宜模型。Agnes 是臨時測試用的便宜貨（8B SEA LLM），之後會換掉。
- **為什麼**：8B 小模型不敢下判斷、只講場面話，是參數量的硬限制，prompt 救不回。分流/Plan/清晰度判定這種中樞決策不能放它。
- **邊界**：Agnes 不能聯網是「沒掛搜尋工具」的接線問題，不是模型笨。兩件事分開看。
- **註**：fast mode（Opus 更貴換更快）與省錢需求衝突，不採用。

## D7. MVP 階段技術紅線
- **決策**：禁用 Postgres、Redis、Docker、雲端服務。儲存一律 SQLite。
- **為什麼**：降複雜度 + 資料隱私 + 先證明核心假設再談規模。
- **可推翻條件**：核心驗證完、確定要規模化時再評估。

## D8. 腦庫與審計日誌是兩個平行儲存層，不可混用
- **決策**：decision_log（routing_events）記「發生過什麼」（append-only 審計）；腦庫記「該知道什麼」（可讀可更新的知識/脈絡）。兩者都用 SQLite 但分開。
- **為什麼**：用途不同。審計是追錯，腦庫是記憶與決策脈絡。混在一起會兩邊都做不好。
- **後續**：腦庫透過統一介面（read_knowledge / write_knowledge）讀寫，agent 不直接碰資料庫。

## D9. 開發順序：先驗證核心細胞，再做外圍
- **決策**：優先證明 Maker→Checker 兩 agent 循環能收斂並交付，再做 UI、MCP 擴充、多 agent、外部接入。
- **為什麼**：護城河是協作引擎本身。引擎跑不通，UI/外圍做得再漂亮也產不出可交付的 MVP。多次被閒聊按鈕、UI bug 等外圍任務分散注意力，確認核心優先。
- **否決**：否決「先把輸入端/UI 體驗做完美再驗證引擎」的順序。

## D10. 腦庫 = 全系統共用一份（第一層），砍掉 agent 私有成長記憶
- **決策**：腦庫只做「全系統共用的知識層」——專案常識、SOP、決策脈絡。所有 agent 透過 read_knowledge / write_knowledge 讀同一份。
- **為什麼**：記憶其實分三層——(1) 共用長期知識 (2) 任務級交接上下文 (3) agent 私有成長記憶。第二層已由任務 context + decision_log 涵蓋；第三層是「會學習的 agent」，研究等級、沉沒成本極高，MVP 碰它等於填無底洞。
- **否決 / 邊界**：否決「每個 agent 各自一份可成長的私有記憶」。腦庫不負責讓 agent 變聰明，只負責讓全系統記得同一份常識與決策。
- **可推翻條件**：核心循環驗證完、且明確需要 agent 累積經驗時，再評估第三層。

## D11. 分流靠「信心分數」決定要不要反問，不硬猜
- **決策**：classifier 判斷分流（direct/align）時同時輸出信心分數。信心 ≥ 門檻（初設 0.8，可調，放設定檔）→ 直接走判斷；信心 < 門檻 → 不硬分流，反問使用者一句（給 A/B 選項，非開放式）。
- **為什麼**：不該逼分流在「猜對/猜錯」二選一。模型沒把握時停下來問，比硬猜安全。「檢查 agent 聯通狀況」被判 direct（confidence 0.7）是硬猜出錯的具體案例。
- **前置依賴**：信心分數必須由夠好的模型產生（見 D6）。agnes 等小模型可能過度自信、亂報信心，此機制會失靈。必須與「classifier 換好模型」綁在一起做。
- **邊界**：反問要給具體選項錨點（例如「A. 執行一次就好 / B. 需要程式碼+測試」），不問開放式「你想要什麼」。

---

## D12. classifier 開發期用 OpenRouter 免費中國模型，但要驗信心分數可信度
- **決策**：classifier 開發階段改用 OpenRouter 上的免費中國模型（如 Qwen 系列），透過 LiteLLM 接，模型字串走設定檔。智力足夠分流任務，開發期額度足夠。
- **為什麼**：比 agnes 強、開發期免費。這是過渡方案，不是長久解。
- **必須驗證（關鍵）**：免費模型的 confidence 是否可信？測試要驗——對模糊任務（如「檢查個 agent 聯通狀況」）是否老實報低信心（該觸發 D11 反問）。若過度自信、亂報高分，D11 失靈，須換模型。用「信心報得老不老實」篩選模型。
- **Backlog（現在不處理）**：
  1. 免費模型有速率限制（免費 50 req/天，$10 儲值升 1000/天），流量上來會卡。
  2. 免費路由多半拿 prompt 去訓練；分流碰得到使用者意圖，處理真實使用者資料時不可用免費模型。

---

## D13. 設定欄位命名：plan_model / maker_model / checker_model
- **決策**：settings.json 三個模型欄位命名為 `plan_model`（分類/routing）、`maker_model`（執行）、`checker_model`（驗收）。舊名 `classifier_model` 廢棄。
- **為什麼**：classifier_model 只說「它是分類器」，沒說它在哪個 agent 層。plan/maker/checker 對應架構三層，接手的人或 AI 一眼看出職責。
- **邊界**：`plan_model` 默認指向 `openrouter-classifier`（見 D16）。三個欄位都可在 settings.json 覆蓋，不進程式碼。

## D14. routing 棄「信心閥值」，改三向分類：answer / code / unclear
- **決策**：classifier 不再輸出 0–1 信心分數，改輸出三個明確 category：`answer`（問答直答）/ `code`（需可驗收成果）/ `unclear`（真的無法判斷）。`unclear` 觸發 `clarify_routing` 模式，問使用者 A/B。
- **為什麼**：gpt-oss-120b 是推理模型，reasoning 過後才輸出，commit 後信心幾乎都在 0.85–0.99，閾值 0.8 等於無效。信心分數本身在推理模型上不可信賴。三向分類讓「不確定」成為一等公民，語意比閥值更穩定。
- **否決**：否決「調整信心閥值」的方向——根本問題是推理模型不輸出低信心，調閾值沒用。
- **實作**：`response_format={"type":"json_object"}` 強制結構輸出；system prompt 指定 category 只能是三個值之一；任何解析失敗 fallback → `unclear`（寧可多問不猜）。

## D15. maker_model 欄位曾是死欄位（已修）
- **決策**：`settings["maker_model"]` 現在會覆蓋 `mapping.py` 的硬編碼，生效優先序：settings.json > mapping.py > triple.model。
- **為什麼**：原始實作 maker.py 直接用 `triple.model`（來自 mapping.py），settings 寫什麼 maker 都看不到，是靜默失效的 bug。
- **Backlog**：maker 的 *預設*模型仍是 mapping.py 的 `agnes`，開發期夠用但不夠強（見 D17）。

## D16. gpt-oss-120b:free（OpenRouter）定為開發期 classifier 預設
- **決策**：`plan_model` 預設 alias 為 `openrouter-classifier`，指向 `openrouter/openai/gpt-oss-120b`，via OpenRouter 免費額度。
- **為什麼**：試過 Qwen 系列（全部速率受限，Venice provider pool 共享），gpt-oss-120b 實際可用、推理能力支撐三向分類。需要 `max_tokens=2000` 讓推理模型有 CoT 空間才能輸出有效 JSON。
- **邊界**：免費路由限制與訓練資料疑慮同 D12 backlog，此為開發期暫定。

## D17. maker 需要強力 coding 模型（待換，現仍 agnes）
- **決策**：maker 應換成能真正寫程式的模型（DeepSeek V3 或 gpt-oss-120b），而非 8B 的 agnes。
- **為什麼**：D15 修好接線後，問題浮現：欄位通了，但 maker 預設仍是 agnes。核心細胞驗證（D9）要求 Maker 真能寫出通過 pytest 的程式碼，agnes 能力不足。
- **狀態**：Backlog。接線已修，換預設模型是下一步，需 Ryan 拍板模型字串。
- **v3 更新**：此決策在 v3 角色重構後已不適用 — Scream 接手執行層，maker_model 不再為 AgentOS 的主要執行路徑。模型選擇由 Scream Code 環境決定，不再由 settings.json 的 maker_model 控制。

## D18. Agnes 定位：多模態工具接入層，非文字主力（v3 更新）
- **原始決策**：Agnes 的正確用途是圖片/影片理解（多模態能力），掛在 MCP 工具層。不用於文字生成、推理、寫程式等主力任務。
- **為什麼**：Agnes 是透過 `apihub.agnes-ai.com` 接入的 API 服務，非本機 8B 模型。文字品質低於 Sonnet/DeepSeek，但多模態是獨特差異化能力。
- **v3 實際發現**：Agnes API 實際提供 **5 個模型**，我們只用了其中一個：
  | 模型 | 能力 | 目前使用 |
  |---|---|---|
  | `agnes-2.0-flash` | 文字 + 視覺理解（看圖） | ✅ converse 閒聊、checker_fallback |
  | `agnes-image-2.1-flash` | **圖片生成** | ❌ 未接入 |
  | `agnes-image-2.0-flash` | **圖片生成**（舊版） | ❌ 未接入 |
  | `agnes-video-v2.0` | **影片理解/生成** | ❌ 未接入 |
  | `agnes-1.5-flash` | 舊版文字 | ❌ 未使用 |
- **關鍵缺陷**：我們的 Gemini 線路（super-engine）只能傳文字，無法傳圖片。Agnes-2.0-flash 是目前系統中**唯一能「看圖」的模型**。image/video 系列模型則是系統中**唯一能產圖/產影片的模型**。
- **邊界**：Agnes 不適合高品質文字生成／推理／寫程式。image/video 模型需整合為 AgentOS executor 後才能在系統中使用。
- **可推翻條件**：若未來接上其他多模態模型（如 Gemini API 直接接入），Agnes 角色可重新評估。

---

## 待決策（尚未拍板，留給後續）
- ~~maker 模型字串換成 DeepSeek V3 或 gpt-oss-120b（D17 後續行動，需 Ryan 拍板）。~~ **（v3 已過時 — Scream 直接控制執行模型，此決策不再適用）**
- align 階段 Plan 的輸出結構，以及多 agent 派工的拆解粒度。
- 真沙箱隔離方案（目前 subprocess 跑同機 temp dir，有安全債，記 backlog）。

---

## D19. executor registry 統一 executor 調度，移除硬編碼 subprocess spawn
- **決策**：新增 `orchestrator/executor_registry.py`，提供 `register()` / `get()` / `list_all()` / `run()` 四介面。`maker.py` 的 `_make_via_claude_code()` 移除，改走 registry。
- **為什麼**：原本 claude-code executor 的 spawn 邏輯直接寫死在 maker.py 裡，要加第二個 executor（super-engine）就要複製貼上。registry 讓加 executor 變成插拔式的。
- **否決**：否決「繼續在 maker.py 加 if-else」。registry pattern 比 config-driven 工廠模式更簡單，MVP 夠用。
- **邊界**：registry 不接管 prompt 組合邏輯（仍留在 maker.py），只負責 spawn + 回 stdout。

## D20. super-engine type 系統：subprocess / super-engine / super-engine-warm
- **決策**：executor 三種 type：
  - `subprocess`（預設）— binary + flags + prompt_flag + model
  - `super-engine` — binary + args + prompt 尾綴（Node.js Playwright 腳本）
  - `super-engine-warm` — HTTP POST 到常駐 daemon（不 spawn）
- **為什麼**：每個 type 的命令建構邏輯不同。用 type 字段區分比在 args 裡塞 magic flag 更清楚。
- **否決**：否決「統一用一個 type 靠 args 硬拆」。
- **可推翻條件**：若有統一的 A2A protocol 取代 HTTP daemon，可棄用 super-engine-warm type。

## D21. Keep-warm daemon 模式：HTTP server 取代反覆 subprocess spawn
- **決策**：`super-engine/ask-daemon.ts` — 啟動時開一次 Brave，監聽 localhost:3456。後續 POST /ask 直接重用瀏覽器，不重開。registry 的 `super-engine-warm` type 透過 HTTP 與 daemon 溝通。
- **為什麼**：one-shot `node ask.ts` 每次要開瀏覽器 + 載入 profile + 導航頁面，耗時 3-5s。daemon 模式把 Gemini 從 64s 降到 2.3s（28x 加速）。
- **否決**：否決「用 stdin/stdout pipe 保持瀏覽器 alive」— HTTP 更標準、好 debug、未來可接多個 client。
- **邊界**：daemon 目前不支援 headless（GenSpark 封鎖 headless Chromium）。Gemini headless 也失敗，需要進階反偵測。

## D22. TUI 方向取代 React desktop app
- **決策**：React desktop app（Tauri）廢棄，改 terminal UI。GSAP 8 skills 已讀取（`~/gbrain/.claude/skills/`），作為 TUI 前端動畫參考。
- **為什麼**：React desktop 太重、debug 太多（WebSocket race, 前端狀態機, Tauri build 問題）。TUI 更輕量、更符合 CLI 辦公室定位。
- **否決**：否決「繼續修 React app」。引擎核心才是護城河，UI 先求有再求美。
- **可推翻條件**：TUI prototype 證明無法滿足基本交互需求時，可重回 web UI 評估。

## D23. v3 角色重新定位：Scream = 計劃 + 執行，Opus 非 maker
- **決策**：Scream Code 從「Planner + Maker（寫 brief → AgentOS call LLM）」改為「計劃 + 執行（自己 call LLM、寫 code、判斷交付）」。AgentOS 移除 maker proxy 角色，退為純基礎設施（safety gate / audit log / registry / 腦庫）。Opus 4.8（GenSpark）不再是 maker_model，回歸顧問角色，不進產線。
- **為什麼**：v2 架構中 Scream 只寫 brief，實際執行依賴 AgentOS 調用 LLM，而 AgentOS 的 maker_model 指向 GenSpark（Opus 4.8），導致（1）Opus 被當成執行層而非顧問，（2）Scream 的執行能力被低估。v3 讓 Scream 直接執行，AgentOS 回歸基礎設施本職，角色分工更清晰。
- **否決 / 邊界**：否決「繼續讓 AgentOS 當 maker proxy」— 零智力基礎設施不該有執行職責。否決「Opus 當 maker_model」— 顧問不進產線。
- **影響範圍**：PROJECT.md / ARCHITECTURE.md / README.md 核心敘事全面更新；data/settings.json 的 maker_model 欄位降級為參考用途；maker.py / loop.py 的程式碼保留不動，僅更新註解。
- **可推翻條件**：若 Scream Code 環境無法勝任執行角色，可重回 AgentOS maker proxy 模式，但屆時 maker_model 不應指向顧問角色。
