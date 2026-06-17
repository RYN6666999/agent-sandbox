"""Tests for /converse endpoint — chat path, no task routing."""
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app

client = TestClient(app)


def _mock_litellm(content: str = "這是閒聊回應"):
    """Build a mock streaming litellm response."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    return iter([chunk])


# ── /converse does NOT enter task routing ────────────────────────────────────

class TestConverseNeverRoutes:
    def test_converse_returns_converse_mode(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "你是誰？", "history": []})
        assert r.status_code == 200
        assert r.json()["mode"] == "converse"
        assert "session_id" in r.json()

    def test_converse_does_not_call_classify_intent(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            with patch("api.main._classify_intent") as mock_cls:
                client.post("/converse", json={"message": "測試", "history": []})
        mock_cls.assert_not_called()

    def test_converse_does_not_call_needs_clarification(self):
        with patch("litellm.completion", return_value=_mock_litellm()):
            with patch("orchestrator.clarify.needs_clarification") as mock_nc:
                client.post("/converse", json={"message": "測試", "history": []})
        mock_nc.assert_not_called()

    def test_converse_short_input_does_not_clarify(self):
        """「測試」 two chars — used to trigger clarify gate in /chat, must NOT here."""
        with patch("litellm.completion", return_value=_mock_litellm()):
            r = client.post("/converse", json={"message": "測試", "history": []})
        assert r.json()["mode"] == "converse"


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
        # history + current message
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

        # last 10 history + 1 current = 11
        assert len(captured["messages"]) == 11

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
