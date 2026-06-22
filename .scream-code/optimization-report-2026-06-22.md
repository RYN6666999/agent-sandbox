# AgentOS 技術優化報告

> 梳理視角：Ponytail（懶=高效，刪>加，梯子）× Military-Grade（spec→contract→guard，可追溯，guard 不可繞）
> 基準：master @ e82bac1，340 tests pass
> 日期：2026-06-22

---

## 0. super-engine 砍掉的影響

**結論：不用它＝零功能影響，可保留（休眠）。但「保留」不是零成本。**

證據：
- `maker.py:make()` 三層 fallback，**預設走 litellm**。super-engine 只在 `TaskSpec.executor` 或 `settings.maker_model` 明指時才走。
- 自修復迴圈（`inspector → runner → maker → checker → heartbeat`）**完全不 import** super-engine。`checker.py` 只有一行「剝 GenSpark/Gemini UI 雜訊」的防禦性解析，非依賴。
- 砍掉只失去「瀏覽器白嫖 GenSpark(Opus)/Gemini 免費版」的省錢路徑，改用付費 litellm API。核心一根毛不掉。

Carrying cost（保留但不用仍要付的）：Playwright + Brave profile + node_modules 維護面、誤導接手者的 surface area、全 repo 唯一脆的東西（網頁改版/封鎖即斷）。

決策樹：確定付費 API → 直接 `git rm` super-engine；可能要省錢 → 保留但標 dormant，別讓它假裝主路徑。（本報告採後者，已在 README 標註。）

---

## 1. 軍工級視角：spec → contract → guard 可追溯鏈

四支柱在「跑一個任務」這條線上是真的。問題在元層級——專案守自己的紀律了嗎？

| 軍工要件 | 現況 | 判定 |
|---|---|---|
| 邊界 runtime 驗證（safeParse） | `/queue/push` 對 `req.spec` 做 `TaskSpec(**spec)`，失敗回 422 | ✅ |
| 真實 guard（不接受幻覺綠燈） | `checker.py` 真開 subprocess 跑 pytest，10/2/0 客觀分 | ✅ |
| 可追溯 | `decision_log` 兩表，單 request_id 查完整鏈 | ✅ |
| 危險紅線先擋 | `safety.py` 純規則 0 LLM | ✅ |
| guard 不可繞過 | 原本 ❌ 無 CI，340 測試只在手動跑才守 → **本批已補 `.github/workflows/test.yml`** | ✅（修復後） |
| contract 單一 source-of-truth | `gen_contracts.py` 原 docstring 自打臉（spec.md 與 MODEL_BODIES 雙真相手動同步）→ **本批已改為誠實單一真相** | ✅（修復後） |

最大的洞（已補）：蓋了要求「真驗收」的辦公室，自己的測試卻沒門禁。沒 CI＝guard 預設就是跳過狀態。

---

## 2. Ponytail 視角：梯子、死重、刪 > 加

| 死重 / 違規 | 證據 | 動作 |
|---|---|---|
| `api/main.py` 1141 行 | 違反自訂 800 上限，35 端點擠一檔 | **拆 `api/routes/*`（P1，另開 PR，本批未做）** |
| `.sdd/` 100 殭屍 tracked 檔 | `.gitignore` 已含但早於 ignore 進版控 | ✅ 本批 `git rm -r --cached .sdd/` |
| `langgraph` 死 dep | pyproject 還掛，專案 code 零 import，README 已棄用 | ✅ 本批刪 |
| `OPTIMIZATION.md` stale「69 測試」 | 實際 340 | ✅ 本批改 |
| 測試 mock 密度高 | ~364 mock refs vs 340 test | 不刪 mock；340 綠燈別當行為保證，真行為靠 `checker` subprocess + `test_e2e` 14 項，那 14 項該擴 |

---

## 3. 優化清單（依投報比）

| 優先 | 項目 | 狀態 |
|---|---|---|
| P0 | CI：`.github/workflows/test.yml`（uv sync + guard_contracts + pytest） | ✅ 本批 |
| P0 | `git rm -r --cached .sdd/` | ✅ 本批 |
| P1 | 拆 `api/main.py` → `api/routes/*` | ⏳ 另開 PR（風險高，不混入機械批次） |
| P1 | contract 真相分裂修正 | ✅ 本批（docstring 誠實化） |
| P2 | super-engine 標 dormant | ✅ 本批 |
| P2 | 刪 langgraph、修 OPTIMIZATION.md 69 | ✅ 本批 |

---

## 4. 不要做（YAGNI 反建議）

- 別把「非 code 任務的 Claude CLI 評分」包裝成客觀驗收——它本質是 LLM 主觀分。誠實標示「pytest-able 才有真 guard」比假裝四支柱全覆蓋更軍工。
- 別硬幹 super-engine headless 繞過——GenSpark 已封，成本 > 收益，backlog 正確擱置。
- 別讓任何 agent 執行期改 prompt——`OPTIMIZATION.md` 第六節自己立的紅線，守住。

---

## 一句話

code 品質贏在自律與真 guard，但專案原本沒拿自己的紀律管自己。本批補 CI（guard 從手動變不可繞過）+ 清死重，把基礎設施層從 8/10 拉向 9/10。剩 P1 拆 `api/main.py` 另開 PR。
