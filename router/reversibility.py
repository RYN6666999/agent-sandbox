"""分類表 → reversibility loader。

從分類表決定「可回退性」：containable / escaping。
新任務類預設 escaping/human，直到證明可關得住。

初版分類表（Ryan 2026-07-24 拍）：
  🟢 containable — 本地檔案寫入、純計算、重構、gbrain 讀取、brief 草稿、pytest
  🟠 escaping — 網路請求、花錢、發訊息、git push、系統設定、gbrain 寫入、未知
"""
from typing import Literal


# ── 分類表（可回退性硬地板） ──────────────────────────────────────────────
# 真值表：任務類名 → 可回退性
_REVERSIBILITY_TABLE: dict[str, Literal["containable", "escaping"]] = {
    "file_write":      "containable",   # 限 sandbox workspace 內
    "compute_draft":   "containable",   # 純計算/分析/草稿
    "refactor_local":  "containable",   # 本地重構
    "gbrain_read":     "containable",   # query/get/search
    "brief_draft":     "containable",   # 只產不發
    "local_test":      "containable",   # pytest
    "network_call":    "escaping",      # 外部 API
    "costly_compute":  "escaping",      # 花錢/大量 token
    "send_message":    "escaping",      # LINE/TG/email
    "git_push":        "escaping",      # 遠端 repo
    "system_change":   "escaping",      # launchd/系統設定
    "gbrain_write":    "escaping",      # 邊界，放寬待拍
}


def classify_reversibility(task_class: str) -> Literal["containable", "escaping"]:
    """從分類表查出任務類的可回退性。

    不在表上的任務類預設回 escaping（最嚴）。
    """
    return _REVERSIBILITY_TABLE.get(task_class, "escaping")


def is_containable(task_class: str) -> bool:
    """捷徑：任務類是否關得住。"""
    return classify_reversibility(task_class) == "containable"


def all_classifications() -> dict[str, Literal["containable", "escaping"]]:
    """回傳完整分類表（唯讀拷貝）。"""
    return dict(_REVERSIBILITY_TABLE)
