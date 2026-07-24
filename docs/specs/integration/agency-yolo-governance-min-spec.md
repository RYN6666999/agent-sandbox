# Agency + YOLO Governance 最小落地規格

版本: v0.1
日期: 2026-07-24
狀態: Draft for implementation

## 1) 目標

把 YOLO 從全域捷徑改成可審計的授權政策，避免 Agency 發起任務時靜默繞過人類監督。

核心原則
- Passive source: 可在 containable 條件下使用 YOLO override
- Agency source: 預設不可使用 YOLO override
- 只有明確政策開啟時，Agency source 才可 YOLO override

## 2) 名詞與決策來源

decision_source 枚舉
- passive
- agency
- human_manual
- system_replay

lane 枚舉
- deny
- human
- sandbox
- auto

## 3) 最小政策 Schema

policy_id: agency-yolo-v1
mode: enforce
rules:
  - name: passive-containable-yolo
    when:
      decision_source: passive
      reversible_actual: containable
      lane_before_override: human
      yolo_enabled: true
    then:
      allow_override_to: sandbox
      human_gate_bypassed: true

  - name: agency-default-no-yolo
    when:
      decision_source: agency
      lane_before_override: human
    then:
      allow_override_to: none
      human_gate_bypassed: false

  - name: agency-explicit-preauth
    when:
      decision_source: agency
      reversible_actual: containable
      lane_before_override: human
      agency_yolo_preauthorized: true
      yolo_enabled: true
    then:
      allow_override_to: sandbox
      human_gate_bypassed: true

  - name: non-containable-never-yolo
    when:
      reversible_actual: escaping
    then:
      allow_override_to: none
      human_gate_bypassed: false

## 4) 審計欄位（第一步先加）

每筆 scoring audit 至少要有
- event_id: string
- ts: ISO-8601
- decision_source: string
- task_class: string
- reversible_actual: containable | escaping
- lane_before_override: deny | human | sandbox | auto
- lane_after_override: deny | human | sandbox | auto
- override_applied: boolean
- override_policy_id: string | null
- human_gate_bypassed: boolean
- yolo_enabled: boolean
- agency_delegate_enabled: boolean
- outcome: pass | fail | deny | escalate
- error: string | null

一致性約束
- override_applied = false 時，lane_before_override 必須等於 lane_after_override
- human_gate_bypassed = true 時，lane_before_override 必須是 human
- decision_source = agency 且 agency_yolo_preauthorized != true 時，不可出現 human->sandbox override

## 5) 告警規則（dashboard + alert）

告警視窗
- short_window: 1h
- long_window: 24h

建議閾值
- sandbox_success_rate_1h < 0.85: warning
- sandbox_success_rate_1h < 0.70: critical
- agency_human_bypass_count_1h > 0: critical（當 policy=agency-default-no-yolo）
- human_to_sandbox_override_rate_24h 急升 > 2x: warning
- deny_rate_1h > baseline_24h * 2: warning

自動保險絲
- 觸發 critical 時：
  - set yolo_enabled=false（或）
  - set agency_delegate_enabled=false
  - 產生事件 auto_recovery_triggered

## 6) 上線順序

Phase A 觀測先行（不改行為）
- 只加審計欄位與一致性檢查
- 連續 soak 2-3 天

Phase B 政策收斂
- 啟用 agency-default-no-yolo
- Passive 保留 containable yolo override

Phase C 小流量委派
- 開啟 agency delegate canary（例如 5% 任務）
- 監控告警與保險絲事件

Phase D 擴大
- 無 critical 事件連續 72h 才提高流量

## 7) 驗收條件

功能驗收
- 可在單筆審計記錄看出 lane_before 與 lane_after
- 可查出所有 human_gate_bypassed=true 的事件來源
- agency source 在預設政策下無 bypass 事件

運行驗收
- dashboard 有短窗與長窗
- critical 事件可自動觸發保險絲
- 保險絲觸發有完整審計記錄

## 8) 最小測試清單

單元測試
- policy evaluator: passive 可 override、agency 預設不可 override
- schema validator: 一致性約束生效

整合測試
- decision_source=agency 且 lane=human 時，不應被 yolo 改到 sandbox
- decision_source=passive 且 containable+human+yolo 時，可改到 sandbox
- alert engine 在閾值觸發時產生 critical 事件

回歸測試
- 既有 scoring lane 不因新增欄位而改變（Phase A）
