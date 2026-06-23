# Model Floor Benchmark — 最低可用的 maker 模型

> 問題：自修復迴圈的 maker（寫 code 的那隻）最低能用多便宜的模型？
> 方法：鷹架 harness（輸出契約 + 格式範例 + 一行 CoT + **把 pytest 輸出翻譯成可行動回饋**）
> 跑小型 coding 套件，oracle = 真跑 pytest，retry ≤ 4 輪。
> 重跑：`OPENROUTER_API_KEY=... python scripts/model_floor_bench.py`（`--bare` 看無鷹架對照）。
> 快照日期：2026-06-23。

## 套件

4 題：`two_sum` / `roman_to_int` / `valid_parens` / `group_anagrams`。模型看題目 + oracle，
oracle 含 held-out case（防硬背）。

## Floor sweep（鷹架，笨 → 強）

| 模型 | pass | 可靠度（多跑） | 可用？ |
|---|---|---|---|
| llama-3.2-1b | 3/4 | 抖 | ✗ |
| llama-3.2-3b | 2/4 | 3×2/4（穩定低） | ✗ |
| **gemma-3-4b** | 4/4 | 3×4/4 | ✓ |
| **qwen-2.5-7b** | 4/4 | 3×4/4 | ✓ |
| **llama-3.1-8b** | 4/4 | 6/7（一次 3/4） | ✓ |
| gemma-3-12b | 4/4 | — | ✓ |
| deepseek-chat | 4/4 | — | ✓ |
| gpt-4o-mini | 4/4 | — | ✓ |

**地板 = 4B（gemma-3-4b）**。但「最低」不是看參數量看世代：gemma-3-4b（4B，新）穩過，
llama-3.2-3b（3B，舊）只有 2/4。

## 鷹架有沒有撐起弱模型？（bare vs 鷹架，A/B）

| 模型 | bare | 鷹架 | lift |
|---|---|---|---|
| llama-3.2-1b | 3/4 | 3/4 | +0 |
| llama-3.2-3b | 1/4 | 2/4 | **+1** |
| qwen-2.5-7b | 3/4 | 4/4 | **+1** |

鷹架（回饋翻譯 + 輸出契約）對邊界模型值約 **+1 題**。救不了太弱的（1B/3B 仍 < 滿分）。
關鍵是把「raw pytest log」翻成「你的 code 沒 parse / assert X 失敗」這種可行動訊息。

## 成本（OpenRouter 實價，$/百萬 token）

| 模型 | in | out | 可用 |
|---|---|---|---|
| **llama-3.1-8b** | **0.020** | **0.030** | ✓ |
| qwen-2.5-7b | 0.040 | 0.100 | ✓ |
| gemma-3-4b | 0.050 | 0.100 | ✓ |
| gemma-3-12b | 0.050 | 0.150 | ✓ |
| gemma-3-27b | 0.080 | 0.160 | ✓ |
| llama-3.2-3b | 0.051 | 0.335 | ✗ |
| gpt-4o-mini | 0.150 | 0.600 | ✓ |
| deepseek-chat | 0.200 | 0.800 | ✓ |

**價格不跟參數量走**：4B 的 gemma 跟 7B 的 qwen 同價（~0.05/0.10）。

## 結論

- **maker_model = `openrouter/meta-llama/llama-3.1-8b-instruct`** — 最省（輸出 0.030，比 qwen/gemma 那群便宜 ~3x）又夠穩（6/7 滿分）。maker 以輸出為主，這項最重要。
- 保守 fallback = `qwen-2.5-7b`（3×4/4 鐵穩，貴 ~3x）。
- **gemma-3-4b 不選**：被 qwen-7b 壓制（同輸出價、qwen 輸入更便宜、一樣穩）。
- **gemma-4 不可用**：OpenRouter free 變體 429（無供給）、paid slug BadRequest。Google 真實只到 Gemma 3。

## 注意

`scripts/model_floor_bench.py` 會花錢（真打 OpenRouter）。4 題小套件、單次跑，低端有變異——
要當真請多跑幾次看可靠度。這是 maker 選型的對照基準，不是嚴謹 eval（對照 `OPTIMIZATION.md` 的評測集構想）。
