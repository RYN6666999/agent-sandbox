"""Tests for orchestrator/safety.py — dangerous-command gate."""
import pytest
from orchestrator.safety import is_dangerous


# ── should trigger ────────────────────────────────────────────────────────────

class TestDangerousCommands:
    def test_rm_rf(self):
        ok, triggers = is_dangerous("rm -rf /tmp/data")
        assert ok is True
        assert any("rm" in t.lower() for t in triggers)

    def test_rm_rf_no_space(self):
        ok, _ = is_dangerous("rm -rf ./build")
        assert ok is True

    def test_drop_table(self):
        ok, triggers = is_dangerous("DROP TABLE users;")
        assert ok is True

    def test_drop_table_lowercase(self):
        ok, _ = is_dangerous("drop table orders")
        assert ok is True

    def test_truncate_table(self):
        ok, _ = is_dangerous("TRUNCATE TABLE logs;")
        assert ok is True

    def test_delete_from_no_where(self):
        ok, _ = is_dangerous("DELETE FROM sessions;")
        assert ok is True

    def test_push_force_long(self):
        ok, _ = is_dangerous("git push origin main --force")
        assert ok is True

    def test_push_force_short(self):
        ok, _ = is_dangerous("git push -f origin main")
        assert ok is True

    def test_push_force_flag_only(self):
        ok, _ = is_dangerous("push --force")
        assert ok is True

    def test_chinese_clear_db(self):
        ok, _ = is_dangerous("清空資料庫然後重啟服務")
        assert ok is True

    def test_format_disk(self):
        ok, _ = is_dangerous("格式化硬碟 /dev/sda")
        assert ok is True

    def test_truncate_no_table_keyword(self):
        ok, _ = is_dangerous("truncate the_table")
        assert ok is True

    def test_redirect_to_dev(self):
        ok, _ = is_dangerous("cat /dev/null > /dev/sda")
        assert ok is True


# ── should NOT trigger (business-logic / safe) ────────────────────────────────

class TestSafeCommands:
    def test_git_push_no_force(self):
        ok, _ = is_dangerous("git push origin main")
        assert ok is False

    def test_chinese_delete_duplicates(self):
        ok, _ = is_dangerous("刪除重複資料並整理表格")
        assert ok is False

    def test_delete_with_where(self):
        # DELETE FROM ... WHERE ... — has WHERE, should not match bare pattern
        ok, _ = is_dangerous("DELETE FROM users WHERE id = 5")
        assert ok is False

    def test_normal_task(self):
        ok, _ = is_dangerous("寫一個算房貸月付的函式並附 pytest")
        assert ok is False

    def test_drop_column(self):
        # DROP COLUMN is schema migration, not table destruction; not in list
        ok, _ = is_dangerous("ALTER TABLE t DROP COLUMN old_col")
        assert ok is False

    def test_remove_file_specific(self):
        # rm without -r/-rf: single file, acceptable
        ok, _ = is_dangerous("rm output.txt")
        assert ok is False

    def test_empty_string(self):
        ok, triggers = is_dangerous("")
        assert ok is False
        assert triggers == []
