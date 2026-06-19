# 協議：任務拆解

> **用途**：把大任務拆成可平行執行、可獨立驗收的子任務。
> **時機**：收到複雜任務，範圍跨多個檔案或多個領域時

---

## 啟動條件

以下情況**必須**先拆解再執行：
- [x] 任務涉及 3 個以上檔案的修改
- [x] 任務可分成獨立的多個步驟（如：前端 + 後端 + 測試）
- [x] 任務需要不同專長的 executor（如：寫程式 + 戰略判斷）
- [x] 任務預計執行時間 > 5 分鐘

以下情況**不需要**拆解：
- 單一檔案小修改
- 單一 executor 能完成的任務
- 已經很明確且已拆好的任務

---

## 拆解原則

1. **每個子任務可獨立驗收**
   - 有明確的完成條件
   - 不需要等其他子任務完成才知道對錯
   
2. **子任務之間依賴越少越好**
   - 優先找無依賴的子任務先做
   - 有依賴的排先後順序

3. **每個子任務交給最適合的 executor**
   - 寫程式 → Claude Code
   - 戰略判斷 → Opus（gbrain）
   - 簡單子任務 → 小模型
   - 不能 deleg 的 → Scream 自己做

---

## 拆解模板

```markdown
## 原始任務

<使用者的原始需求>

## 拆解結果

### 子任務 A：<名稱>
- Executor：<claude-code / subagent / opus / scream >
- 目標：
- 輸入：
- 預期輸出：
- 依賴於：無（或子任務 X）
- 驗收標準：

### 子任務 B：<名稱>
- Executor：
- 目標：
- 輸入：
- 預期輸出：
- 依賴於：
- 驗收標準：

## 執行順序

1. 子任務 A（獨立）
2. 子任務 B（獨立，可與 A 平行）
3. 子任務 C（依賴 A 和 B 完成後）

## 合併驗收

全部完成後檢查：
- [ ] 所有子任務驗收通過
- [ ] 整合後整體功能正常
- [ ] 無 side effect
```

---

## 範例

**原始任務**：為專案加上 CI/CD pipeline，含測試自動執行、lint 檢查、部署到 staging

```
### 子任務 A：CI 設定 (GitHub Actions)
- Executor：claude-code
- 目標：建立 .github/workflows/ci.yml，push 時自動跑 pytest
- 輸入：現有 pyproject.toml、tests/ 目錄結構
- 預期輸出：可用的 CI yaml 檔案
- 依賴於：無
- 驗收標準：push 後 GitHub Actions 觸發且 pytest 全過

### 子任務 B：Lint 設定
- Executor：claude-code
- 目標：加入 ruff 設定到 pyproject.toml，修正現有 lint error
- 輸入：現有程式碼
- 預期輸出：ruff clean
- 依賴於：無
- 驗收標準：ruff check . 回傳 0

### 子任務 C：Deploy script
- Executor：claude-code
- 目標：寫 deploy.sh，自動部署到 staging server
- 輸入：staging server 連線資訊
- 預期輸出：deploy.sh + README
- 依賴於：子任務 A
- 驗收標準：執行 deploy.sh 後 staging 更新且健康檢查過

→ 子任務 A 和 B 可平行執行
→ 子任務 C 等 A 完成後執行
```