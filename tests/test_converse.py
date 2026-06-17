"""Tests for /converse endpoint — blocking chat path, no task routing."""
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app

client = TestClient(app)

REPLY_TEXT = "這是閒聊回應"


def _mock_litellm(content: str = REPLY_TEXT):
    """Mock non-streaming litellm response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


# ── /converse returns reply in HTTP body ──────────────────────────────────────

class TestConverseHttpReply:
    def test_reply_in_body(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "你好", "history": []})
        assert r.status_code == 200
        assert r.json()["mode"] == "converse"
        assert r.json()["reply"] == REPLY_TEXT

    def test_no_session_id_in_response(self):
        """Blocking path — no WS session needed."""
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "hi", "history": []})
        assert "session_id" not in r.json()

    def test_timeout_returns_error_message(self):
        import asyncio
        with patch("litellm.completion", side_effect=asyncio.TimeoutError()):
            r = client.post("/converse", json={"message": "hi", "history": []})
        assert r.status_code == 200
        assert "逾時" in r.json()["reply"]

    def test_llm_error_returns_error_message(self):
        with patch("litellm.completion", side_effect=Exception("quota exceeded")):
            r = client.post("/converse", json={"message": "hi", "history": []})
        assert r.status_code == 200
        assert "錯誤" in r.json()["reply"]


# ── /converse does NOT enter task routing ────────────────────────────────────

class TestConverseNeverRoutes:
    def test_converse_mode_returned(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "你是誰？", "history": []})
        assert r.json()["mode"] == "converse"

    def test_classify_intent_not_called(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            with patch("api.main._classify_intent") as mock_cls:
                client.post("/converse", json={"message": "測試", "history": []})
        mock_cls.assert_not_called()

    def test_short_input_not_clarified(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "測試", "history": []})
        assert r.json()["mode"] == "converse"
        assert "reply" in r.json()


# ── /converse sends history to LLM ───────────────────────────────────────────

class TestConverseHistory:
    def test_history_passed_to_llm(self):
        history = [
            {"role": "user", "text": "你好"},
            {"role": "system", "text": "你好！有什麼可以幫你？"},
        ]
        captured = {}

        def capture_call(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _mock_litellm()

        with patch("litellm.completion", side_effect=capture_call):
            client.post("/converse", json={"message": "繼續", "history": history})

        msgs = captured["messages"]
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["content"] == "繼續"

    def test_history_capped_at_10(self):
        history = [{"role": "user", "text": f"msg{i}"} for i in range(20)]
        captured = {}

        def capture_call(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _mock_litellm()

        with patch("litellm.completion", side_effect=capture_call):
            client.post("/converse", json={"message": "new", "history": history})

        assert len(captured["messages"]) == 11  # last 10 + current

    def test_empty_history_ok(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "hello", "history": []})
        assert r.status_code == 200


# ── /chat task path: safety still fires ──────────────────────────────────────

class TestChatSafetyStillActive:
    def test_dangerous_task_blocked_in_chat(self):
        r = client.post("/chat", json={"task": "rm -rf /tmp/data"})
        assert r.json()["mode"] == "confirm_dangerous"

    def test_normal_task_not_blocked(self):
        with patch("api.main._classify_intent", return_value={
            "decision": "direct", "decision_source": "test",
            "matched_keyword": None, "confidence": 0.9,
            "classifier_model": None, "fallback_reason": None, "details": {},
        }):
            with patch("api.main._run_direct_and_push"):
                r = client.post("/chat", json={"task": "寫一個 hello world 函式"})
        assert r.json()["mode"] == "direct"
