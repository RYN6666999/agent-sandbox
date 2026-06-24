"""Tests for maker brain retrieval."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from contracts.task_spec import TaskSpec


class TestMakerBrainRetrieval:
    def _spec(self, why="implement add function"):
        return TaskSpec(
            why=why,
            io_example={"input": "1,2", "expected_output": "3"},
            taste=[], boundaries=[], stop_on_metric="quality", max_rounds=1,
        )

    def test_retrieve_brain_returns_formatted_context(self):
        from orchestrator.maker import _retrieve_brain_context
        fake_results = [
            {"key": "gene/coding/add-function", "content": "之前實作過整數相加"},
        ]
        with patch("orchestrator.knowledge.search_knowledge", return_value=fake_results):
            ctx = _retrieve_brain_context("implement add function")
        assert "Relevant past experiences" in ctx
        assert "add-function" in ctx

    def test_retrieve_brain_empty_returns_empty(self):
        from orchestrator.maker import _retrieve_brain_context
        with patch("orchestrator.knowledge.search_knowledge", return_value=[]):
            ctx = _retrieve_brain_context("implement add function")
        assert ctx == ""

    def test_brain_context_injected_into_system_prompt(self):
        """Verify that brain context ends up in the system message."""
        from orchestrator.maker import _call_litellm
        from unittest.mock import patch as _patch

        from router.policy import PolicyResult
        from contracts.routing_triple import RoutingTriple
        from litellm import Choices, Message, ModelResponse
        from litellm.utils import Usage
        
        spec = self._spec()
        fake_results = [{"key": "gene/coding/add", "content": "之前經驗"}]
        
        # We mock heavily to avoid real LLM calls, just verify the system prompt
        with _patch("orchestrator.knowledge.search_knowledge", return_value=fake_results):
            with _patch("orchestrator.maker.route") as mock_route:
                mock_route.return_value = PolicyResult(
                    triple=RoutingTriple(model="test", skills=[], mcp_tools=[], confidence=0.9),
                    violations=[],
                    requires_human_confirm=False,
                )
                with _patch("orchestrator.maker._resolve", return_value={}):
                    with _patch("orchestrator.maker.litellm.completion") as mock_llm:
                        mock_llm.return_value = ModelResponse(
                            id="test",
                            choices=[Choices(message=Message(content="ok"))],
                            usage=Usage(prompt_tokens=10, completion_tokens=5),
                        )
                        _call_litellm(spec)