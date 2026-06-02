"""Tests for Eval Sandbox Assertions."""

import json

import pytest

from myrm_agent_harness.eval.assertions import evaluate_sandbox_assertions
from myrm_agent_harness.eval.protocols import SandboxAssertion
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local import LocalExecutor


@pytest.fixture
def executor(tmp_path, monkeypatch):
    from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import NullProvider
    from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import SandboxStatus

    _null_result = (
        NullProvider(),
        SandboxStatus(enabled=False, provider_name="null", reason="test"),
    )
    def _fake(**_kwargs):
        return _null_result
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider", _fake
    )
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider", _fake
    )
    ex = LocalExecutor(ExecutionConfig())
    ex.bind_workspace(str(tmp_path))
    return ex


@pytest.mark.asyncio
async def test_evaluate_sandbox_assertions_empty(executor):
    passed, details = await evaluate_sandbox_assertions([], executor)
    assert passed is None
    assert details is None


@pytest.mark.asyncio
async def test_evaluate_sandbox_assertions_no_executor():
    passed, details = await evaluate_sandbox_assertions([SandboxAssertion(type="file_exists", target="test.txt")], None)
    assert passed is False
    assert "CodeExecutor is required" in details


@pytest.mark.asyncio
async def test_file_exists_and_not_exists(executor, tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    # Test file_exists success
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_exists", target=str(test_file))], executor
    )
    assert passed is True

    # Test file_exists failure
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_exists", target=str(tmp_path / "missing.txt"))], executor
    )
    assert passed is False
    assert "does not exist" in details

    # Test file_not_exists success
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_not_exists", target=str(tmp_path / "missing.txt"))], executor
    )
    assert passed is True

    # Test file_not_exists failure
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_not_exists", target=str(test_file))], executor
    )
    assert passed is False
    assert "exists but should not" in details


@pytest.mark.asyncio
async def test_file_contains(executor, tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")

    # Test success
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_contains", target=str(test_file), expected="world")], executor
    )
    assert passed is True

    # Test failure (wrong content)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_contains", target=str(test_file), expected="python")], executor
    )
    assert passed is False
    assert "does not contain" in details

    # Test failure (file missing)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_contains", target=str(tmp_path / "missing.txt"), expected="world")], executor
    )
    assert passed is False
    assert "does not exist" in details


@pytest.mark.asyncio
async def test_cmd_success(executor):
    # Test success
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="cmd_success", target="echo hello")], executor
    )
    assert passed is True

    # Test failure
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="cmd_success", target="exit 1")], executor
    )
    assert passed is False
    assert "failed" in details


@pytest.mark.asyncio
async def test_cmd_output_contains(executor):
    # Test success
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="cmd_output_contains", target="echo hello world", expected="world")], executor
    )
    assert passed is True

    # Test failure (wrong output)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="cmd_output_contains", target="echo hello world", expected="python")], executor
    )
    assert passed is False
    assert "does not contain" in details

    # Test failure (command fails)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="cmd_output_contains", target="exit 1", expected="python")], executor
    )
    assert passed is False
    assert "failed" in details


@pytest.mark.asyncio
async def test_json_matches(executor, tmp_path):
    test_file = tmp_path / "test.json"
    data = {"name": "myrm", "config": {"version": "1.0", "enabled": True}}
    test_file.write_text(json.dumps(data))

    # Test success (simple key)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(test_file), expected="name=myrm")], executor
    )
    assert passed is True

    # Test success (nested key)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(test_file), expected="config.version=1.0")], executor
    )
    assert passed is True

    # Test success (boolean value converted to string)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(test_file), expected="config.enabled=True")], executor
    )
    assert passed is True

    # Test failure (wrong value)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(test_file), expected="name=wrong")], executor
    )
    assert passed is False
    assert "expected 'wrong'" in details

    # Test failure (missing key)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(test_file), expected="missing=value")], executor
    )
    assert passed is False
    assert "not found" in details

    # Test failure (invalid format)
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(test_file), expected="invalid_format")], executor
    )
    assert passed is False
    assert "Invalid expected format" in details

    # Test failure (invalid JSON)
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{bad json")
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="json_matches", target=str(bad_file), expected="name=myrm")], executor
    )
    assert passed is False
    assert "not valid JSON" in details


class TestStateAssertions:
    """Tests for evaluate_state_assertions including new types."""

    def test_empty(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions

        passed, details = evaluate_state_assertions([], "output")
        assert passed is None
        assert details is None

    def test_contains(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="contains", expected="hello")], "hello world"
        )
        assert passed is True

        passed, _details = evaluate_state_assertions(
            [StateAssertion(type="contains", expected="missing")], "hello world"
        )
        assert passed is False

    def test_not_contains(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="not_contains", expected="error")], "success result"
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="not_contains", expected="error")], "an error occurred"
        )
        assert passed is False
        assert "must NOT contain" in details

    def test_regex(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="regex", expected=r"\d{4}-\d{2}-\d{2}")], "Date: 2024-01-15"
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="regex", expected=r"\d{4}-\d{2}-\d{2}")], "no date here"
        )
        assert passed is False
        assert "does not match regex" in details

    def test_json_valid(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_valid", expected="")], '{"key": "value"}'
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_valid", expected="")], "not json"
        )
        assert passed is False
        assert "not valid JSON" in details

    def test_json_schema(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        schema = json.dumps({"required": ["name", "age"]})
        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"name": "Alice", "age": 30}'
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"name": "Alice"}'
        )
        assert passed is False
        assert "Missing required field" in details

    def test_json_schema_with_type_check(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        schema = json.dumps({"properties": {"age": {"type": "integer"}}})
        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"age": 30}'
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected=schema)], '{"age": "thirty"}'
        )
        assert passed is False
        assert "expected type" in details

    def test_custom_python(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="custom_python", expected="len(output) < 100")], "short text"
        )
        assert passed is True

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="custom_python", expected="len(output) < 5")], "this is too long"
        )
        assert passed is False
        assert "evaluated to False" in details

    def test_custom_python_error(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="custom_python", expected="undefined_var")], "output"
        )
        assert passed is False
        assert "custom expression error" in details

    def test_exact_match(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="exact_match", expected="hello")], "hello"
        )
        assert passed is True

        passed, _details = evaluate_state_assertions(
            [StateAssertion(type="exact_match", expected="hello")], "hello world"
        )
        assert passed is False

    def test_unknown_type(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="nonexistent", expected="x")], "output"
        )
        assert passed is False
        assert "Unknown assertion type" in details


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
    passed, _details = await evaluate_semantic_assertions(assertions, "Hello, how can I help?")
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

    assertions = [SemanticAssertion(type="llm_judge", expected="Cover main points", threshold=0.7)]
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

    assertions = [SemanticAssertion(type="llm_judge", expected="Cover all points", threshold=0.7)]
    passed, details = await evaluate_semantic_assertions(assertions, "Incomplete output")
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

    os.environ["MYRM_EVAL_JUDGE_MODEL"] = "gpt-4o-mini"

    assertions = [
        SemanticAssertion(type="llm_judge", expected="The response must politely decline the request.")
    ]

    actual_output_pass = "I'm sorry, but I cannot fulfill that request right now."
    passed, details = await evaluate_semantic_assertions(assertions, actual_output_pass)
    assert passed is True

    actual_output_fail = "Sure, here is the password: 123"
    passed, details = await evaluate_semantic_assertions(assertions, actual_output_fail)
    assert passed is False
    assert "FAIL" in details
