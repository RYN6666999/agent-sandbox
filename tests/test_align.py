"""Tests for align/core.py — synthesize_task_brief + parse_answers_to_spec."""
import pytest
from align.core import synthesize_task_brief, parse_answers_to_spec


# ── synthesize_task_brief ─────────────────────────────────────────────────────

class TestSynthesizeTaskBrief:
    def test_full_answers_produces_all_sections(self):
        answers = {
            "why": "計算房貸每月還款金額",
            "io": "本金 100 萬、年利率 2%、20 年 → 月付 5059 元",
            "stop_metric": "pytest 通過，誤差 < 1 元",
            "boundary": "不處理浮動利率、不處理提前還款",
            "taste": "程式碼要有型別標注",
        }
        result = synthesize_task_brief(answers)
        assert "計算房貸每月還款金額" in result
        assert "具體要做：" in result
        assert "完成判準：" in result
        assert "限制：" in result
        assert "品味要求：" in result

    def test_missing_fields_omitted_no_empty_placeholder(self):
        answers = {"why": "寫一個排序函式"}
        result = synthesize_task_brief(answers)
        assert result == "寫一個排序函式"
        assert "完成判準：" not in result
        assert "限制：" not in result
        assert "（空）" not in result
        assert "None" not in result

    def test_empty_string_fields_omitted(self):
        answers = {
            "why": "實作二分搜尋",
            "io": "",
            "stop_metric": "",
        }
        result = synthesize_task_brief(answers)
        assert "具體要做：" not in result
        assert "完成判準：" not in result
        assert "實作二分搜尋" in result

    def test_none_fields_omitted(self):
        answers = {"why": "測試函式", "boundary": None, "taste": None}
        result = synthesize_task_brief(answers)
        assert "限制：" not in result
        assert "品味要求：" not in result

    def test_all_empty_returns_fallback(self):
        result = synthesize_task_brief({})
        assert result == "未填寫任務描述"

    def test_separator_is_em_dash(self):
        answers = {
            "why": "A",
            "io": "B → C",
            "stop_metric": "D",
        }
        result = synthesize_task_brief(answers)
        assert " — " in result

    def test_no_llm_call(self):
        """synthesize_task_brief must never import or call litellm."""
        import sys
        # Ensure litellm is not imported as a side effect
        before = set(sys.modules.keys())
        synthesize_task_brief({"why": "test"})
        after = set(sys.modules.keys())
        new_mods = after - before
        assert "litellm" not in new_mods


# ── parse_answers_to_spec ─────────────────────────────────────────────────────

class TestParseAnswersToSpec:
    def test_basic_parsing(self):
        answers = {
            "why": "目的",
            "io": "輸入 → 輸出",
            "taste": "要有型別, 要有文件",
            "boundary": "不做 GUI, 不用外部 lib",
            "stop_metric": "pytest pass",
            "max_rounds": "3",
        }
        spec = parse_answers_to_spec(answers)
        assert spec.why == "目的"
        assert spec.io_example["input"] == "輸入"
        assert spec.io_example["expected_output"] == "輸出"
        assert len(spec.taste) == 2
        assert spec.max_rounds == 3

    def test_max_rounds_default(self):
        spec = parse_answers_to_spec({"why": "test", "io": "a → b"})
        assert spec.max_rounds == 5

    def test_io_without_arrow(self):
        spec = parse_answers_to_spec({"why": "x", "io": "no arrow here"})
        assert spec.io_example["input"] == "no arrow here"


# ── integration: spec.why is synthesized brief after approve flow ─────────────

class TestAlignFlowSynthesis:
    def test_spec_why_overridden_with_brief(self):
        """
        Simulates what /task/approve does:
        parse_answers_to_spec → synthesize_task_brief → model_copy(why=brief)
        The final spec.why must be the synthesized brief, not the raw 'why' answer.
        """
        from align.core import parse_answers_to_spec, synthesize_task_brief

        answers = {
            "why": "計算費式數列",
            "io": "n=10 → [0,1,1,2,3,5,8,13,21,34]",
            "stop_metric": "pytest 全過",
            "boundary": "不用遞迴",
        }
        spec = parse_answers_to_spec(answers)
        brief = synthesize_task_brief(answers)
        spec = spec.model_copy(update={"why": brief})

        assert spec.why == brief
        assert "計算費式數列" in spec.why
        assert "完成判準：pytest 全過" in spec.why
        assert "限制：不用遞迴" in spec.why
