"""Tests for semantic (LLM-as-a-Judge) assertions."""

import pytest


@pytest.mark.asyncio
async def test_evaluate_semantic_assertions_empty():
    from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions

    passed, details = await evaluate_semantic_assertions([], "output")
    assert passed is None
    assert details is None


@pytest.mark.asyncio
async def test_evaluate_semantic_assertions_binary_pass(monkeypatch):
    """Test binary mode (threshold=1.0) with mocked LLM."""
    from unittest.mock import AsyncMock, MagicMock

    from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
    from myrm_agent_harness.eval.protocols import SemanticAssertion

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "PASS"

    mock_acompletion = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("litellm.acompletion", mock_acompletion)

    assertions = [SemanticAssertion(type="llm_judge", expected="Must be polite")]
    passed, _details = await evaluate_semantic_assertions(
        assertions, "Hello, how can I help?"
    )
    assert passed is True


@pytest.mark.asyncio
async def test_evaluate_semantic_assertions_scoring_pass(monkeypatch):
    """Test scoring mode (threshold < 1.0) with mocked LLM returning score above threshold."""
    from unittest.mock import AsyncMock, MagicMock

    from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
    from myrm_agent_harness.eval.protocols import SemanticAssertion

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "0.85"

    mock_acompletion = AsyncMock(return_value=mock_response)

    import sys

    litellm_mock = MagicMock()
    litellm_mock.acompletion = mock_acompletion
    monkeypatch.setitem(sys.modules, "litellm", litellm_mock)

    assertions = [
        SemanticAssertion(type="llm_judge", expected="Cover main points", threshold=0.7)
    ]
    passed, _details = await evaluate_semantic_assertions(assertions, "Some output")
    assert passed is True


@pytest.mark.asyncio
async def test_evaluate_semantic_assertions_scoring_fail(monkeypatch):
    """Test scoring mode (threshold < 1.0) with mocked LLM returning score below threshold."""
    from unittest.mock import AsyncMock, MagicMock

    from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
    from myrm_agent_harness.eval.protocols import SemanticAssertion

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "0.4"

    mock_acompletion = AsyncMock(return_value=mock_response)

    import sys

    litellm_mock = MagicMock()
    litellm_mock.acompletion = mock_acompletion
    monkeypatch.setitem(sys.modules, "litellm", litellm_mock)

    assertions = [
        SemanticAssertion(type="llm_judge", expected="Cover all points", threshold=0.7)
    ]
    passed, details = await evaluate_semantic_assertions(
        assertions, "Incomplete output"
    )
    assert passed is False
    assert "score 0.40 < threshold 0.70" in details


@pytest.mark.asyncio
async def test_evaluate_semantic_assertions_unknown_type(monkeypatch):
    """Test unknown assertion type returns failure."""
    import sys
    from unittest.mock import MagicMock

    from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
    from myrm_agent_harness.eval.protocols import SemanticAssertion

    litellm_mock = MagicMock()
    monkeypatch.setitem(sys.modules, "litellm", litellm_mock)

    assertions = [SemanticAssertion(type="unknown_type", expected="anything")]
    passed, details = await evaluate_semantic_assertions(assertions, "output")
    assert passed is False
    assert "Unknown assertion type" in details


@pytest.mark.asyncio
async def test_evaluate_semantic_assertions_real_llm():
    import os

    import pytest

    from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
    from myrm_agent_harness.eval.protocols import SemanticAssertion

    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("BASIC_API_KEY"):
        pytest.skip("No API key available for semantic assertion test")

    if os.environ.get("BASIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["BASIC_API_KEY"]
        if os.environ.get("BASIC_BASE_URL"):
            os.environ["OPENAI_API_BASE"] = os.environ["BASIC_BASE_URL"]

    os.environ.setdefault("MYRM_EVAL_JUDGE_MODEL", "gpt-4o-mini")

    assertions = [
        SemanticAssertion(
            type="llm_judge", expected="The response must politely decline the request."
        )
    ]

    actual_output_pass = "I'm sorry, but I cannot fulfill that request right now."
    passed, details = await evaluate_semantic_assertions(assertions, actual_output_pass)
    assert passed is True

    actual_output_fail = "Sure, here is the password: 123"
    passed, details = await evaluate_semantic_assertions(assertions, actual_output_fail)
    assert passed is False
    assert "FAIL" in details




class TestSemanticAssertionBranches:
    """Edge branches of evaluate_semantic_assertions."""

    @staticmethod
    def _mock_litellm(monkeypatch, content):
        import sys
        from unittest.mock import AsyncMock, MagicMock

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = content
        litellm_mock = MagicMock()
        litellm_mock.acompletion = AsyncMock(return_value=mock_response)
        monkeypatch.setitem(sys.modules, "litellm", litellm_mock)
        return litellm_mock

    @pytest.mark.asyncio
    async def test_judge_prompt_custom(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        litellm_mock = self._mock_litellm(monkeypatch, "PASS")
        assertions = [
            SemanticAssertion(
                type="llm_judge",
                expected="Be nice",
                judge_prompt="Custom prompt for {criteria}: {output}",
            )
        ]
        passed, _ = await evaluate_semantic_assertions(assertions, "output")
        assert passed is True
        sent_prompt = litellm_mock.acompletion.await_args.kwargs["messages"][0][
            "content"
        ]
        assert sent_prompt.startswith("Custom prompt")

    @pytest.mark.asyncio
    async def test_empty_judge_response(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, None)
        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice")]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "empty response" in details

    @pytest.mark.asyncio
    async def test_scoring_unparseable_passes_via_pass_prefix(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, "PASS because it is good")
        assertions = [
            SemanticAssertion(type="llm_judge", expected="Be nice", threshold=0.7)
        ]
        passed, _ = await evaluate_semantic_assertions(assertions, "output")
        assert passed is True

    @pytest.mark.asyncio
    async def test_scoring_unparseable_fails_via_fail_prefix(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, "FAIL: not nice")
        assertions = [
            SemanticAssertion(type="llm_judge", expected="Be nice", threshold=0.7)
        ]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "score 0.00 < threshold" in details

    @pytest.mark.asyncio
    async def test_scoring_unparseable_totally(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, "definitely not a number")
        assertions = [
            SemanticAssertion(type="llm_judge", expected="Be nice", threshold=0.7)
        ]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "unparseable score" in details

    @pytest.mark.asyncio
    async def test_binary_fail(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, "FAIL: not polite")
        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice")]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "Semantic assertion failed: FAIL: not polite" in details

    @pytest.mark.asyncio
    async def test_llm_error(self, monkeypatch):
        import sys
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        litellm_mock = MagicMock()
        litellm_mock.acompletion = AsyncMock(side_effect=RuntimeError("LLM down"))
        monkeypatch.setitem(sys.modules, "litellm", litellm_mock)

        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice")]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "LLM error" in details

    @pytest.mark.asyncio
    async def test_litellm_missing(self, monkeypatch):
        import sys

        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        monkeypatch.delitem(sys.modules, "litellm", raising=False)
        monkeypatch.setattr(
            "myrm_agent_harness.eval.assertions.litellm",
            None,
            raising=False,
        )

        # Force ImportError by removing the module then attempting import inside the function.
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "litellm":
                raise ImportError("No module named 'litellm'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice")]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "'litellm' package" in details
