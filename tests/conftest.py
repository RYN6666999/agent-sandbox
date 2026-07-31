"""測試永遠不准碰正式 ratchet。

2026-07-31 事故：`tests/test_scoring_router.py` 的 autouse cleanup fixture 對
`router.ratchet._RATCHET_PATH` 做 unlink，而那個路徑預設就是正式的
`data/ratchet.json`。跑一次 pytest = 信任狀態歸零，與 07-25 `git clean` 殺掉
ratchet 同類，只是換一個觸發源。CI 也會踩。

`router.ratchet._DATA_DIR` 在 import 時就從 `AGENTOS_RATCHET_DATA_DIR` 解析，
所以這裡必須在任何 test module 被 import 之前把環境變數設好 —— conftest 早於
test module 載入，這是唯一來得及的位置。
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="agentos-ratchet-test-"))
os.environ["AGENTOS_RATCHET_DATA_DIR"] = str(_TMP)


def pytest_report_header(config):
    return f"ratchet data dir (isolated): {_TMP}"


def test_guard_not_prod():
    """自檢：萬一有人把 conftest 的 import 順序弄壞，這條會先紅。"""
    from router import ratchet
    prod = Path(__file__).parent.parent / "data"
    assert ratchet._DATA_DIR.resolve() != prod.resolve(), (
        f"測試指到正式資料夾 {ratchet._DATA_DIR} —— 跑下去會刪掉正式 ratchet"
    )
