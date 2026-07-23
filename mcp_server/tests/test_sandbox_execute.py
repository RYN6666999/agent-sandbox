"""AgentOS MCP Server — 完整測試 (v0.2.2)。

執行：AGENTOS_WORK_DIR=/tmp/agentos-test-w python3 -m pytest mcp_server/tests/ -v
"""

import json
import os
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

MCP_SERVER = [__import__("sys").executable, "-m", "mcp_server.server"]
TEST_DIR = Path(tempfile.mkdtemp(prefix="agentos-test-"))
WORK_DIR = TEST_DIR / "workspace"
SNAP_DIR = TEST_DIR / "snapshots"


_INIT = {"jsonrpc":"2.0","id":0,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},
    "clientInfo":{"name":"test","version":"0.1"}
}}


def _mcp_raw(*requests) -> dict:
    """送 initialize + requests，回傳 {id: JSON-RPC response}（不解 content）。"""
    env = os.environ.copy()
    env["AGENTOS_WORK_DIR"] = str(WORK_DIR)
    env["AGENTOS_SNAPSHOT_DIR"] = str(SNAP_DIR)
    env["AGENTOS_AUDIT_PATH"] = str(SNAP_DIR.parent / "audit.log")
    _root = str(Path(__file__).resolve().parents[2])
    proc = subprocess.Popen(MCP_SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env, cwd=_root)
    payload = "".join(json.dumps(m) + "\n" for m in (_INIT, *requests))
    try:
        stdout, _ = proc.communicate(input=payload, timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {}
    out = {}
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        d = json.loads(line)
        if "id" in d:
            out[d["id"]] = d
    return out


def _mcp_call(**kwargs) -> dict:
    responses = _mcp_raw({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
        "name":"sandbox_execute","arguments":kwargs
    }})
    d = responses.get(1)
    if d is None:
        return {"status":"timeout"}
    for c in d.get("result",{}).get("content",[]):
        if c.get("type")=="text":
            return json.loads(c["text"])
    return {"status":"error","stdout":json.dumps(d)[:200]}


@pytest.fixture(autouse=True)
def ws():
    WORK_DIR.mkdir(parents=True,exist_ok=True)
    (WORK_DIR / "test.txt").write_text("hello world")
    (WORK_DIR / "sub").mkdir(exist_ok=True)
    (WORK_DIR / "sub" / "nested.txt").write_text("nested")
    yield
    import shutil
    shutil.rmtree(TEST_DIR, ignore_errors=True)


# ═══════════════ A. Root Identity ═══════════════

class TestRootIdentity:
    def test_workspace_root_symlink_rejected(self):
        link = TEST_DIR / "fake_root"
        os.symlink(str(WORK_DIR), link)
        env = os.environ.copy()
        env["AGENTOS_WORK_DIR"] = str(link)
        proc = subprocess.Popen(MCP_SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env,
                                cwd=str(Path(__file__).resolve().parents[2]))
        init = json.dumps({"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}})+"\n"
        call = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sandbox_execute","arguments":{"operation":"get_cwd"}}})+"\n"
        stdout, stderr = proc.communicate(input=init+call, timeout=10)
        assert "Config error" in stderr or "error" in stdout

    def test_root_replaced_after_start(self):
        """Server 啟動後 root 被換成另一個目錄 → workspace_identity_changed。"""
        from mcp_server.sandbox.workspace import WorkspaceHandle
        wh = WorkspaceHandle(WORK_DIR)
        new_dir = TEST_DIR / "new_root"
        new_dir.mkdir()
        (new_dir / "evil.txt").write_text("evil")
        os.rename(str(WORK_DIR), str(TEST_DIR / "old_root"))
        os.rename(str(new_dir), str(WORK_DIR))
        with pytest.raises(Exception):
            wh.dup_fd()
        os.rename(str(WORK_DIR), str(new_dir))
        os.rename(str(TEST_DIR / "old_root"), str(WORK_DIR))
        wh.close()

    def test_root_deleted_after_start(self):
        from mcp_server.sandbox.workspace import WorkspaceHandle
        wh = WorkspaceHandle(WORK_DIR)
        import shutil
        shutil.rmtree(str(WORK_DIR))
        WORK_DIR.mkdir()
        with pytest.raises(Exception):
            wh.dup_fd()
        wh.close()

    def test_fd_not_leaking(self):
        """1000 次 operation 後 fd 數不成長（使用 lsof 計數）。"""
        import subprocess
        from mcp_server.sandbox.workspace import WorkspaceHandle
        wh = WorkspaceHandle(WORK_DIR)
        pid = os.getpid()
        def count_fds():
            r = subprocess.run(["lsof", "-p", str(pid), "-F", "f"], capture_output=True, text=True, timeout=5)
            return len([l for l in r.stdout.split("\n") if l.startswith("f") and l[1:].isdigit()])
        before = count_fds()
        for _ in range(1000):
            fd = wh.dup_fd()
            os.close(fd)
        after = count_fds()
        wh.close()
        # Allow small fluctuation (GC timing)
        assert abs(after - before) < 10, f"fd leak: {before} -> {after}"


# ═══════════════ B. Operations ═══════════════

class TestOperations:
    def test_list_directory(self):
        r = _mcp_call(operation="list_directory")
        assert r["status"] == "ok"
        assert "test.txt" in r["stdout"]

    def test_read_file(self):
        r = _mcp_call(operation="read_file", path="test.txt")
        assert r["status"] == "ok"
        assert "hello world" in r["stdout"]

    def test_read_nonexistent(self):
        r = _mcp_call(operation="read_file", path="nope.txt")
        assert r["status"] == "not_found"

    def test_read_directory_as_file(self):
        r = _mcp_call(operation="read_file", path="sub")
        assert r["status"] == "blocked"

    def test_get_cwd(self):
        r = _mcp_call(operation="get_cwd")
        assert r["status"] == "ok"


# ═══════════════ C. Security ═══════════════

class TestSecurity:
    def test_absolute_path_rejected(self):
        r = _mcp_call(operation="read_file", path="/etc/passwd")
        assert r["status"] == "blocked"

    def test_parent_escape_rejected(self):
        r = _mcp_call(operation="read_file", path="../../etc/passwd")
        assert r["status"] == "blocked"

    def test_symlink_rejected(self):
        link = WORK_DIR / "evil"
        os.symlink("/etc/passwd", link)
        r = _mcp_call(operation="read_file", path="evil")
        assert r["status"] in ("blocked", "not_found")

    def test_dir_symlink_rejected(self):
        link = WORK_DIR / "evildir"
        os.symlink("/tmp", link)
        r = _mcp_call(operation="list_directory", path="evildir")
        assert r["status"] in ("blocked", "not_found")

    def test_option_injection_rejected(self):
        r = _mcp_call(operation="read_file", path="--help")
        assert r["status"] == "blocked"

    def test_shell_metachar_rejected(self):
        r = _mcp_call(operation="read_file", path="test;rm -rf /")
        assert r["status"] == "blocked"

    def test_git_status_disabled(self):
        r = _mcp_call(operation="git_status")
        assert r["status"] == "blocked"

    def test_git_log_disabled(self):
        r = _mcp_call(operation="git_log")
        assert r["status"] == "blocked"


# ═══════════════ C2. Write File ═══════════════

class TestWriteFile:
    """write_file：寫入前必 checkpoint，失敗必回退。

    這組是 checkpoint / rollback 路徑第一次被端到端執行 — 在只有唯讀操作的
    時期，兩個模組雖有單元測試但 execute() 走不到。
    """

    @staticmethod
    def _exec(**params):
        """直接呼叫 executor（繞過 MCP 子行程，測得到 checkpoint 內部狀態）。"""
        import tempfile as _tf
        from mcp_server.config import Config
        from mcp_server.sandbox.workspace import WorkspaceHandle
        from mcp_server.sandbox.executor import execute
        os.environ["AGENTOS_WORK_DIR"] = str(WORK_DIR)
        os.environ["AGENTOS_SNAPSHOT_DIR"] = str(SNAP_DIR)
        os.environ["AGENTOS_AUDIT_PATH"] = str(TEST_DIR / "audit.log")
        cfg = Config()
        wh = WorkspaceHandle(cfg.work_dir)
        try:
            return execute(operation=params.pop("operation"), wh=wh, config=cfg,
                           params=params, session_id="t"), cfg
        finally:
            wh.close()

    def test_create_new_file(self):
        r = _mcp_call(operation="write_file", path="new.txt", content="hello")
        assert r["status"] == "ok", r["stderr"]
        assert (WORK_DIR / "new.txt").read_text() == "hello"
        assert r["checkpoint_id"] is not None

    def test_overwrite_then_rollback_restores_original(self):
        (WORK_DIR / "exist.txt").write_text("ORIGINAL")
        r, cfg = self._exec(operation="write_file", path="exist.txt", content="REPLACED")
        assert r["status"] == "ok"
        assert (WORK_DIR / "exist.txt").read_text() == "REPLACED"

        from mcp_server.sandbox.rollback import manual_rollback
        rb = manual_rollback(r["checkpoint_id"], cfg.snapshot_dir)
        assert rb["status"] == "ok", rb
        assert (WORK_DIR / "exist.txt").read_text() == "ORIGINAL"

    def test_rollback_of_new_file_deletes_it(self):
        r, cfg = self._exec(operation="write_file", path="fresh.txt", content="x")
        assert r["status"] == "ok"
        from mcp_server.sandbox.rollback import manual_rollback
        rb = manual_rollback(r["checkpoint_id"], cfg.snapshot_dir)
        assert rb["status"] == "ok"
        assert not (WORK_DIR / "fresh.txt").exists()

    def test_symlink_target_blocked_without_checkpoint(self):
        """symlink 必須在 checkpoint 之前擋掉。

        Checkpoint 用一般路徑操作，_sha256() 會跟隨 symlink 讀到 workspace
        外的檔案。順序錯了就會對 workspace 外的目標建快照。
        """
        outside = TEST_DIR / "OUTSIDE.txt"
        outside.write_text("外部內容")
        os.symlink(str(outside), WORK_DIR / "link.txt")
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        before = len(list(SNAP_DIR.glob("*.json")))

        r = _mcp_call(operation="write_file", path="link.txt", content="PWNED")
        assert r["status"] == "blocked"
        assert "symlink" in r["stderr"]
        assert outside.read_text() == "外部內容"
        assert len(list(SNAP_DIR.glob("*.json"))) == before, "不該為 symlink 建 checkpoint"

    @pytest.mark.parametrize("bad_path", [".env", "secret.txt", "id_rsa", "my.key"])
    def test_forever_denied_paths_not_writable(self, bad_path):
        """快照不了的路徑就不准寫 — checkpoint 的 deny 清單即寫入保護。"""
        r = _mcp_call(operation="write_file", path=bad_path, content="x")
        assert r["status"] == "blocked"
        assert "forever_denied" in r["stderr"]
        assert not (WORK_DIR / bad_path).exists()

    def test_absolute_path_blocked(self):
        assert _mcp_call(operation="write_file", path="/etc/x", content="x")["status"] == "blocked"

    def test_parent_escape_blocked(self):
        assert _mcp_call(operation="write_file", path="../esc.txt", content="x")["status"] == "blocked"
        assert not (TEST_DIR / "esc.txt").exists()

    def test_directory_target_blocked(self):
        r = _mcp_call(operation="write_file", path="sub", content="x")
        assert r["status"] == "blocked"

    def test_missing_path_blocked(self):
        r = _mcp_call(operation="write_file", content="x")
        assert r["status"] == "blocked"
        assert "path required" in r["stderr"]

    def test_oversize_content_blocked_and_rolled_back(self):
        from mcp_server.sandbox.executor import MAX_WRITE_BYTES
        r = _mcp_call(operation="write_file", path="big.txt",
                      content="A" * (MAX_WRITE_BYTES + 1))
        assert r["status"] == "blocked"
        assert r["rollback_applied"] is True
        assert not (WORK_DIR / "big.txt").exists()

    def test_atomic_write_leaves_no_temp_file(self):
        r = _mcp_call(operation="write_file", path="atomic.txt", content="done")
        assert r["status"] == "ok"
        leftovers = [p.name for p in WORK_DIR.iterdir() if ".tmp." in p.name]
        assert leftovers == [], leftovers

    def test_readonly_ops_still_produce_no_checkpoint(self):
        r = _mcp_call(operation="read_file", path="test.txt")
        assert r["status"] == "ok"
        assert r["checkpoint_id"] is None
        assert r["rollback_applied"] is False


# ═══════════════ D. Checkpoint ═══════════════

class TestCheckpoint:
    def test_directory_rejected(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        with pytest.raises(ValueError, match="not a regular file"):
            Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["sub"])

    def test_nested_env_rejected(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        p = WORK_DIR / "pkg"
        p.mkdir()
        (p / ".env").write_text("SECRET")
        with pytest.raises(ValueError, match="forever_denied"):
            Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["pkg/.env"])

    def test_nested_secret_rejected(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        p = WORK_DIR / "pkg"
        p.mkdir()
        (p / "secret.txt").write_text("SECRET")
        with pytest.raises(ValueError, match="forever_denied"):
            Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["pkg/secret.txt"])

    def test_regular_file_allowed(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        ckpt = Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["test.txt"])
        assert ckpt is not None

    def test_archive_0600(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        ckpt = Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["test.txt"])
        mode = stat.S_IMODE(ckpt.archive_path.stat().st_mode)
        assert mode == 0o600

    def test_restore_deleted(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        f = WORK_DIR / "canary.txt"
        f.write_text("canary")
        ckpt = Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["canary.txt"])
        f.unlink()
        r = ckpt.restore()
        assert r["status"] == "ok"
        assert f.read_text() == "canary"

    def test_rollback_removes_new(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        f = WORK_DIR / "canary.txt"
        f.write_text("canary")
        ckpt = Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["canary.txt"])
        new_f = WORK_DIR / "new.txt"
        new_f.write_text("new")
        r = ckpt.restore()
        assert r["status"] == "ok"
        # new.txt is not in allow_paths, should NOT be affected by rollback
        assert new_f.exists(), "file outside allow_paths should be untouched"
        assert f.read_text() == "canary"

    def test_allow_list_untouched(self):
        from mcp_server.sandbox.checkpoint import Checkpoint
        f = WORK_DIR / "canary.txt"
        f.write_text("canary")
        outside = WORK_DIR / "outside.txt"
        outside.write_text("outside")
        ckpt = Checkpoint.create(WORK_DIR, SNAP_DIR, allow_paths=["canary.txt"])
        f.unlink()
        outside.write_text("changed")
        r = ckpt.restore()
        assert outside.read_text() == "changed"


# ═══════════════ E. Schema ═══════════════

class TestSchema:
    def test_unknown_operation_rejected(self):
        r = _mcp_call(operation="rm")
        assert r["status"] == "blocked"

    def test_tools_list_forbids_additional_properties(self):
        """tools/list 對外宣告的 inputSchema 必須關閉 additionalProperties。"""
        responses = _mcp_raw({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})
        tools = responses[1]["result"]["tools"]
        tool = next(t for t in tools if t["name"] == "sandbox_execute")
        schema = tool["inputSchema"]
        assert schema.get("additionalProperties") is False, schema
        # flat API 不得被改成巢狀 model 參數
        assert set(schema["properties"]) == {
            "operation", "path", "content", "session_id"
        }, schema
        assert schema["required"] == ["operation"], schema

    def test_unknown_param_rejected(self):
        """未知參數必須在進 executor 前被擋下，不得回 ok。"""
        responses = _mcp_raw({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{
            "name":"sandbox_execute",
            "arguments":{"operation":"get_cwd","bogus_param":1},
        }})
        result = responses[1]["result"]
        assert result.get("isError") is True, result
        text = "".join(c.get("text","") for c in result.get("content",[]))
        assert "bogus_param" in text, text
        assert "Extra inputs are not permitted" in text, text

    def test_known_params_still_accepted(self):
        """收緊 schema 不得誤傷合法的 flat 呼叫。"""
        r = _mcp_call(operation="read_file", path="test.txt", session_id="s1")
        assert r["status"] == "ok"
        assert "hello world" in r["stdout"]

    def test_allowed_ops_consistency(self):
        from mcp_server.sandbox.executor import ALLOWED_OPS as E
        from mcp_server.gate.rules import ALLOWED_OPS as G
        assert E == G

    def test_toctou_race_read_file(self):
        """TOCTOU race：100 次零外洩。"""
        from mcp_server.sandbox.executor import _execute_read_file, _validate_user_path
        outside = TEST_DIR / "outside.txt"
        outside.write_text("SECRET")
        link = WORK_DIR / "race_link"
        leaks = 0
        total = 100
        from mcp_server.sandbox.workspace import WorkspaceHandle
        wh = WorkspaceHandle(WORK_DIR)
        for i in range(total):
            try:
                if i % 2 == 0:
                    os.symlink(str(outside), link)
                else:
                    link.unlink(missing_ok=True)
                    (WORK_DIR / "race_link").write_text("safe")
            except OSError:
                pass
            try:
                dup = wh.dup_fd()
                parts = _validate_user_path("race_link")
                content = _execute_read_file(dup, parts)
                if "SECRET" in content: leaks += 1
                os.close(dup)
            except Exception:
                pass
            try:
                link.unlink(missing_ok=True)
            except OSError:
                pass
        wh.close()
        assert leaks == 0, f"TOCTOU leak: {leaks}/{total}"

    def test_toctou_race_write_file(self):
        """寫入路徑 TOCTOU：背景 thread 狂換 symlink，寫入零外洩。

        write_file 有兩個時間窗：lstat 檢查→checkpoint、checkpoint→rename。
        背景 thread 持續把目標在「常規檔」與「指向 workspace 外的 symlink」
        之間翻轉，主 thread 反覆走完整寫入路徑。三個不變量：

        1. workspace 外的檔案內容永不被寫入（rename 不跟隨 symlink）
        2. 不殘留 .tmp. 暫存檔（O_EXCL + finally unlink）
        3. checkpoint 永不捕獲 workspace 外的內容 hash
           （_sha256 的 O_NOFOLLOW 關掉 lstat→checkpoint 的 race 窗）

        第 3 條是這個測試催生的修復點：加寫入前，checkpoint 的 _sha256
        會跟隨 symlink，此測試的前身版本在 400 次中有 65 次捕獲外部 hash。
        """
        import threading, json, hashlib
        from mcp_server.config import Config
        from mcp_server.sandbox.workspace import WorkspaceHandle
        from mcp_server.sandbox.executor import execute

        os.environ["AGENTOS_WORK_DIR"] = str(WORK_DIR)
        os.environ["AGENTOS_SNAPSHOT_DIR"] = str(SNAP_DIR)
        os.environ["AGENTOS_AUDIT_PATH"] = str(TEST_DIR / "audit.log")
        cfg = Config()

        outside = TEST_DIR / "toctou_write_outside.txt"
        SENTINEL = "OUTSIDE-UNTOUCHED"
        outside.write_text(SENTINEL)
        out_hash = hashlib.sha256(SENTINEL.encode()).hexdigest()
        target = WORK_DIR / "race_target"

        stop = threading.Event()

        def swapper():
            while not stop.is_set():
                try:
                    target.unlink(missing_ok=True)
                    os.symlink(str(outside), target)
                except OSError:
                    pass
                try:
                    target.unlink(missing_ok=True)
                    target.write_text("regular")
                except OSError:
                    pass

        wh = WorkspaceHandle(WORK_DIR)
        t = threading.Thread(target=swapper, daemon=True)
        t.start()
        total = 300
        outside_writes = 0
        temp_leaks = 0
        ckpt_captured_outside = 0
        try:
            for i in range(total):
                r = execute(operation="write_file", wh=wh, config=cfg,
                            params={"path": "race_target", "content": f"NEW-{i}"},
                            session_id="race")
                if outside.read_text() != SENTINEL:
                    outside_writes += 1
                if any(".tmp." in p.name for p in WORK_DIR.iterdir()):
                    temp_leaks += 1
                cid = r.get("checkpoint_id")
                if cid:
                    mp = SNAP_DIR / f"{cid}.json"
                    if mp.exists():
                        meta = json.loads(mp.read_text())
                        if meta["file_hashes"].get("race_target") == out_hash:
                            ckpt_captured_outside += 1
        finally:
            stop.set()
            t.join(timeout=5)
            wh.close()

        assert outside_writes == 0, f"workspace 逃逸: {outside_writes}/{total} 次外部檔案被寫入"
        assert temp_leaks == 0, f"暫存檔殘留: {temp_leaks} 次"
        assert ckpt_captured_outside == 0, f"checkpoint 捕獲外部內容: {ckpt_captured_outside}/{total}"
        assert outside.read_text() == SENTINEL


# ═══════════════ F. Worker Shadow ═══════════════

class TestWorkerShadow:
    """Shadow worker 測試。

    隔離規則：每個 test 拿到一份新載入的 bridge module，並把所有會寫到
    home 的常數改指到 tmp。絕不寫 ~/agent-sandbox/logs/shadow.jsonl，
    絕不碰全域 kill sentinel /tmp/agentos-shadow-kill，
    也絕不把 AGENTOS_SHADOW_ENABLED 留在 process env（預設保持 0）。
    """

    @pytest.fixture
    def bridge(self, tmp_path, monkeypatch):
        # 模組 import 時會讀 AGENTOS_SHADOW_ENABLED，先確保它不存在，
        # 避免測試順序造成的殘留把 shadow 打開。
        monkeypatch.delenv("AGENTOS_SHADOW_ENABLED", raising=False)

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            f"agentos_bridge_undertest_{tmp_path.name}",
            os.path.expanduser("~/Developer/neuralis/scripts/agentos-aris-bridge.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 用 setattr 而非 monkeypatch.setattr：module 是本次測試專用的拋棄式副本，
        # 不需要還原。更重要的是若 daemon worker thread 在 teardown 後還活著，
        # 還原後的常數會讓它寫回真實 shadow log。不還原就沒有這個窗口。
        mod.SHADOW_LOG = str(tmp_path / "shadow.jsonl")
        mod.SHADOW_KILL_SENTINEL = str(tmp_path / "kill-sentinel")
        mod.SHADOW_SNAPSHOT_DIR = str(tmp_path / "snapshots") + "/"
        mod.SHADOW_ENABLED = True

        yield mod

        mod._shadow_shutdown(timeout=5)

    @staticmethod
    def _assert_isolated(bridge):
        """log 只落在 tmp，真實 shadow log 沒被本測試碰到。"""
        real_log = os.path.expanduser("~/agent-sandbox/logs/shadow.jsonl")
        assert bridge.SHADOW_LOG != real_log
        assert os.environ.get("AGENTOS_SHADOW_ENABLED", "0") == "0"

    def test_queue_full(self, bridge):
        for i in range(30):
            bridge._shadow_call_to_mcp("read", "get_cwd", f"t-{i}")
        time.sleep(0.5)
        bridge._shadow_call_to_mcp("read", "get_cwd", "t-last")
        self._assert_isolated(bridge)

    def test_shutdown_clean(self, bridge):
        bridge._shadow_call_to_mcp("read", "get_cwd", "t-init")
        time.sleep(1)
        bridge._shadow_shutdown(timeout=5)
        time.sleep(1)
        assert bridge._SHADOW_QUEUE.unfinished_tasks == 0
        self._assert_isolated(bridge)

    def test_shadow_log_written_to_tmp_only(self, bridge, tmp_path):
        """正向證明：shadow 事件確實寫進 tmp log，而不是真實 log。"""
        bridge._shadow_call_to_mcp("read", "get_cwd", "t-isolated")
        time.sleep(0.5)
        tmp_log = tmp_path / "shadow.jsonl"
        assert tmp_log.exists(), "shadow log 沒寫到 tmp"
        entries = [json.loads(l) for l in tmp_log.read_text().splitlines() if l.strip()]
        assert any(e.get("entry_id") == "t-isolated" for e in entries), entries
        self._assert_isolated(bridge)