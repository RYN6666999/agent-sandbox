"""Tests for the clarification gate (orchestrator/clarify.py)."""
from unittest.mock import patch, MagicMock

import pytest

from orchestrator.clarify import (
    _is_vague,
    _generate_question,
    needs_clarification,
    merge_task,
)


# ── _is_vague: rule engine ────────────────────────────────────────────────────

class TestIsVague:
    # --- should trigger ---
    def test_action_verb_is_clear(self):
        """'測試' contains action verb '測' → clear, not vague."""
        assert _is_vague("測試") is False

    def test_action_verb_english(self):
        """'test' is an English action verb → clear."""
        assert _is_vague("test") is False

    def test_very_short(self):
        assert _is_vague("hi") is True

    def test_short_no_verb(self):
        assert _is_vague("API 整合") is True  # < 20 chars, no verb

    def test_single_word_no_space(self):
        assert _is_vague("Python") is True

    def test_noun_phrase_no_action(self):
        assert _is_vague("資料庫") is True

    # --- should NOT trigger ---
    def test_complete_task_chinese(self):
        assert _is_vague("幫我寫一個 Python function 計算費式數列前 n 項") is False

    def test_complete_task_english(self):
        assert _is_vague("write a function that reverses a linked list") is False

    def test_question_mark(self):
        assert _is_vague("為什麼 Python 的 GIL 會影響多線程性能？") is False

    def test_question_starter_how(self):
        assert _is_vague("如何使用 asyncio 處理並發任務") is False

    def test_question_starter_english(self):
        assert _is_vague("how do I set up a FastAPI project") is False

    def test_action_verb_build(self):
        assert _is_vague("build a REST API with FastAPI") is False

    def test_action_verb_chinese_implement(self):
        assert _is_vague("實作一個二分搜尋演算法") is False

    def test_explain_verb(self):
        assert _is_vague("explain the difference between list and tuple") is False


# ── Case A: short/vague input triggers clarification ─────────────────────────

class TestNeedsClarificationTriggered:
    def test_short_input_triggers(self):
        """「API」→ should_clarify=True, question is non-empty."""
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "你想對 API 做什麼？"

        with patch("orchestrator.clarify.litellm.completion", return_value=mock_resp):
            should, question = needs_clarification("API")

        assert should is True
        assert len(question) > 0
        assert question  # not empty string

    def test_ambiguous_noun_phrase_triggers(self):
        """Short noun without verb → clarify."""
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "你想對 API 做什麼？"

        with patch("orchestrator.clarify.litellm.completion", return_value=mock_resp):
            should, question = needs_clarification("API")

        assert should is True

    def test_question_is_context_aware(self):
        """Generated question should not be completely generic — mock returns specific text."""
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "你想要對 API 做什麼？"

        with patch("orchestrator.clarify.litellm.completion", return_value=mock_resp):
            _, question = needs_clarification("API")

        assert "API" in question or "?" in question or "？" in question


# ── Case B: complete input does NOT trigger clarification ─────────────────────

class TestNeedsClarificationNotTriggered:
    def test_complete_task_no_llm_call(self):
        """Clear task → False, 0 LLM calls."""
        with patch("orchestrator.clarify.litellm.completion") as mock_llm:
            should, question = needs_clarification("幫我寫一個 Python function 計算費式數列前 n 項")

        assert should is False
        assert question == ""
        mock_llm.assert_not_called()  # 0 LLM calls for clear input

    def test_question_with_mark_no_trigger(self):
        with patch("orchestrator.clarify.litellm.completion") as mock_llm:
            should, _ = needs_clarification("如何優化 SQL 查詢性能？")

        assert should is False
        mock_llm.assert_not_called()

    def test_english_complete_task_no_trigger(self):
        with patch("orchestrator.clarify.litellm.completion") as mock_llm:
            should, _ = needs_clarification("implement a binary search algorithm in Python")

        assert should is False
        mock_llm.assert_not_called()


# ── Case C: after clarification, merged text routes normally (no re-trigger) ──

class TestClarifyThenRoute:
    def test_merged_text_does_not_retrigger(self):
        """
        Original: 「測試」 + answer: 「測 add 函式的邊界情況」
        Merged should be clear enough to NOT trigger clarification again.
        """
        merged = merge_task("測試", "測 add 函式的邊界情況")
        with patch("orchestrator.clarify.litellm.completion") as mock_llm:
            should, _ = needs_clarification(merged)

        # Merged text has action verb + content → should not clarify
        assert should is False
        mock_llm.assert_not_called()

    def test_merge_answer_subsumes_original(self):
        """Answer already contains original keyword → return answer only (no duplication)."""
        result = merge_task("測試", "測 add 函式的邊界情況")
        assert result == "測 add 函式的邊界情況"
        assert "[" not in result  # no bracket markers
        assert "補充" not in result

    def test_merge_answer_unrelated_to_original(self):
        """Original 'API' + answer 'Stripe 金流整合' → concatenated."""
        result = merge_task("API", "Stripe 金流整合")
        assert "API" in result
        assert "Stripe" in result
        assert "[" not in result

    def test_merge_empty_answer_returns_original(self):
        assert merge_task("測試", "") == "測試"

    def test_merge_no_bracket_notation(self):
        """Final merged text must never contain bracket markers."""
        result = merge_task("build", "a FastAPI REST service with auth")
        assert "[補充" not in result
        assert "[clarif" not in result.lower()


# ── LLM fallback on error ─────────────────────────────────────────────────────

class TestLlmFallback:
    def test_llm_error_returns_template_not_raises(self):
        """If LLM fails, _generate_question returns a fallback, never raises."""
        with patch("orchestrator.clarify.litellm.completion", side_effect=Exception("quota")):
            should, question = needs_clarification("API")

        assert should is True
        assert len(question) > 0  # fallback template kicks in
