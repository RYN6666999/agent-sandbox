# Military-Grade Workflow 改善計劃

> 基於 2026-06-20 分析：核心概念（SPEC→guard→IMPL）是對的，但太重且綁定 Next.js 生態

---

## 問題摘要

1. **太重** — 8 步驟全鏈條，小改動也要全餐
2. **鎖 Next.js/Turborepo** — `npm run guard:*` 指令不通用
3. **沒有快速通道** — 不分「小修 bug」vs「大功能開發」
4. **假設專案已有 infra** — 非 LB-nexus 專案無法使用

---

## 改善方向

### 1. 分級流程（最重要）

引入三個等級，取代一條鞭的 8 步驟：

```
等級        適用場景                   流程
────────────────────────────────────────────────
L1 快速修  typo、README、一行邏輯      直接修 → guard:types（5秒）
L2 一般    bug fix、小功能             寫簡易 spec → IMPL → guard:all（5分鐘）
L3 嚴謹    新頁面、新 domain           完整 SPEC→guard→contract→IMPL→guard:all（15分鐘）
```

等級由開發者判斷，不在流程強制。

### 2. 抽象 guard 層

不要把 guard 寫死在 `npm run guard:*`，改成抽象介面：

```yaml
guards:
  types: "npm run typecheck"          # 每個專案自定義
  lint: "npm run lint"
  test: "npm test"
  contract: "npm run guard:contracts"  # 只有 LB-nexus 專案才有
```

Skill 只規定「必須跑哪些 guard」，不規定「怎麼跑」。

### 3. 獨立的 quick-fix 路徑

新增一個 `/military-quick` 子命令或模式：

- 跳過 spec 寫作
- 跳過 contract 生成
- 直接 IMPL → guard:all
- 但要求寫一行 commit message 說明為什麼跳過

### 4. 專案偵測 + 自動降級

Skill 啟動時偵測專案類型：

```
偵測到 openspec/ + packages/contracts/ + turborepo → L3 完整模式
偵測到一般 Python/JS 專案                      → L2 精簡模式（lint + test only）
偵測不到任何工具鏈                              → L1 純心智模型（寫 spec + 手動驗）
```

---

## 實作優先序

```
P0: 分級流程（L1/L2/L3） — 解決「太重」核心痛點
P1: 抽象 guard 層 — 讓 skill 跨專案可用
P2: 專案偵測 + 自動降級 — 提升易用性
P3: 獨立 quick-fix 路徑 — 減少摩擦
```