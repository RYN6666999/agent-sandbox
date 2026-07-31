"""評分函式 — 四維打分 → 四 lane。

純函式、可測。不碰 LLM，不碰網路。

四維：
  可回退性 — 任務類屬關得住組（沙箱可撤）
  可驗證性 — 有客觀訊號證明它對嗎
  信心×歷史 — 同類 ratchet 驗證成功累積
  成本 — 預算內

lane 決定（可回退性是硬地板，不是分數）：
  deny    ← 碰腦/碰裁判/爆硬預算（硬拒，不問分數）
  human   ← escaping 或 沒法驗證 或 信心低 或 全新任務類
  sandbox ← containable + 可驗證 + 歷史夠 but 未畢業 auto
  auto    ← containable + 可驗證 + 歷史夠 **且已簽核進 auto**
"""
from contracts.verdict_v2 import ActionRequest, VerdictV2
from router.reversibility import classify_reversibility, is_containable
from router.ratchet import load_ratchet, RatchetEntry


# ── 常數 ────────────────────────────────────────────────────────────────────
SCORE_REVERSIBILITY_CONTAINABLE = 1.0
SCORE_REVERSIBILITY_ESCAPING = 0.0

SCORE_VERIFIABLE = 1.0
SCORE_UNVERIFIABLE = 0.0

SCORE_COST_WITHIN_BUDGET = 1.0
SCORE_COST_OVER_BUDGET = 0.0

# lane 門檻
# 降級過的 human 類要爬回 sandbox 的信心門檻。
# 升 auto 的門檻不在這裡 —— 那是 ratchet.PASS_THRESHOLD_FOR_AUTO，只有一份。
CONFIDENCE_THRESHOLD_SANDBOX = 0.5
COST_BUDGET_TOKENS = 100_000         # 預算上限（tokens）
COST_BUDGET_COMPUTE = 10_000         # 預算上限（compute units）


def _score_reversibility(request: ActionRequest) -> float:
    """可回退性維度：裁判覆核，不信自報。"""
    actual = classify_reversibility(request.task_class)
    return SCORE_REVERSIBILITY_CONTAINABLE if actual == "containable" else SCORE_REVERSIBILITY_ESCAPING


def _score_verifiability(request: ActionRequest) -> float:
    """可驗證性維度：有客觀訊號嗎？"""
    # 基本判斷：containable 類通常可驗證，escaping 類通常不可驗證
    # 此處可擴充為查驗證註冊表
    if is_containable(request.task_class):
        return SCORE_VERIFIABLE
    return SCORE_UNVERIFIABLE


def _score_confidence_history(entry: RatchetEntry | None) -> float:
    """信心×歷史維度：從 ratchet 履歷算信心分。"""
    if entry is None:
        return 0.0  # 全新任務類 → 信心 0
    total = entry.verified_count + entry.failed_count
    if total == 0:
        return 0.0
    return entry.verified_count / total


def _score_cost(request: ActionRequest) -> float:
    """成本維度：預估用量在預算內嗎？"""
    est = request.cost_estimate
    tokens = est.get("tokens", 0)
    compute = est.get("compute", 0)
    if tokens > COST_BUDGET_TOKENS or compute > COST_BUDGET_COMPUTE:
        return SCORE_COST_OVER_BUDGET
    return SCORE_COST_WITHIN_BUDGET


def _determine_lane(
    request: ActionRequest,
    reversible_score: float,
    verifiability_score: float,
    confidence_score: float,
    cost_score: float,
    entry: RatchetEntry | None,
) -> str:
    """四條 lane 決定邏輯。

    可回退性是硬地板：escaping 類永遠封頂 human。

    信心分**不擋進沙箱，只擋畢業**（2026-07-31 修冷啟動死鎖）：
    沙箱是「拿真結果」的地方，樣本從那裡來。拿信心分擋沙箱會鎖死 ——
    沒樣本 → 信心 0 → 進不了沙箱 → 永遠沒樣本。ratchet.json 的 level
    才是信任狀態的權威，信心分交給 ratchet.update_ratchet 管升降級。
    """
    # 硬拒條件：成本爆預算
    if cost_score == SCORE_COST_OVER_BUDGET:
        return "deny"

    # 可回退性硬地板
    actual = classify_reversibility(request.task_class)
    if actual == "escaping":
        return "human"

    # 可驗證性閘
    if verifiability_score < SCORE_VERIFIABLE:
        return "human"

    # 全新任務類（ratchet 沒這筆）→ human。人先看過、Ryan 決定要不要放進沙箱觀察
    if entry is None:
        return "human"

    # ratchet 明確標 human（含曾降級的）→ 要靠信心爬回來。
    # 注意：降級後信心分不會自己回升（human lane 不產樣本），
    # 這是刻意的 —— 降級是懲罰，回沙箱要 Ryan 手動重置 level。
    if entry.level == "human":
        if confidence_score < CONFIDENCE_THRESHOLD_SANDBOX:
            return "human"
        return "sandbox"

    # ratchet 已放在 sandbox → 進沙箱真跑、累積樣本。
    # 升 auto 是 ratchet + Ryan 簽核的事（policy b），不在這裡決定
    if entry.level == "sandbox":
        return "sandbox"

    # level == "auto"：已經 Ryan 簽核過（signoff_auto 才寫得進來）
    return "auto"


def score(request: ActionRequest) -> VerdictV2:
    """四維打分 → 回 VerdictV2。

    不碰 LLM，不碰網路。純函式。
    """
    # 1. 載入 ratchet 履歷
    ratchet_entries = load_ratchet()
    entry = ratchet_entries.get(request.task_class)

    # 2. 四維打分
    reversible_score = _score_reversibility(request)
    verifiability_score = _score_verifiability(request)
    confidence_score = _score_confidence_history(entry)
    cost_score = _score_cost(request)

    # 3. 綜合分數（加權平均）
    composite = (
        reversible_score * 0.35 +
        verifiability_score * 0.25 +
        confidence_score * 0.25 +
        cost_score * 0.15
    )

    # 4. 決定 lane
    lane = _determine_lane(
        request, reversible_score, verifiability_score,
        confidence_score, cost_score, entry,
    )

    # 5. 決定 outcome
    outcome = "pass" if lane in ("sandbox", "auto") else "fail"

    # 6. 建 VerdictV2
    actual = classify_reversibility(request.task_class)
    return VerdictV2(
        action_id=request.action_id,
        status="pass" if outcome == "pass" else "retry",
        score=composite,
        feedback=f"lane={lane} reversible={actual} confidence={confidence_score:.2f}",
        passed=(outcome == "pass"),
        source="scoring-router",
        violations=[],
        lane=lane,
        outcome=outcome,
        reversible_actual=actual,
        objective_signal={"kind": "scoring", "detail": f"composite={composite:.2f}"},
        cost_actual={"tokens": request.cost_estimate.get("tokens", 0), "compute": request.cost_estimate.get("compute", 0)},
        committed=False,
        gate={"decision": "allow" if lane in ("sandbox", "auto") else "deny" if lane == "deny" else "escalate", "reason": f"lane={lane}"},
        digest=f"sha256:{hash(request.action_id)}",
    )