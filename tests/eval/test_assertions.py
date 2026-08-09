"""Tests for Eval Sandbox Assertions."""

import json
import sys
from pathlib import Path

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
    # test_suite assertions run `python -m pytest` inside the sandbox bash session;
    # point the shared venv at the interpreter running the tests so pytest resolves.
    config = ExecutionConfig()
    config.local.shared_venv_path = sys.prefix
    ex = LocalExecutor(config)
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


@pytest.mark.asyncio
async def test_test_suite_junit_pass(executor, tmp_path):
    """A pytest suite writing JUnit XML with all green tests passes."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_app.py").write_text("def test_ok(): assert True\n")

    assertion = SandboxAssertion(
        type="test_suite",
        target="python -m pytest -q .wb_bench/tests --junitxml=.wb_bench/results.xml",
        result_file=".wb_bench/results.xml",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions([assertion], executor, scores_out=scores)
    assert passed is True
    assert scores["pass_rate"] == 1.0
    assert scores["tests_total"] == 1.0


@pytest.mark.asyncio
async def test_test_suite_junit_partial_fail(executor, tmp_path):
    """A pytest suite with failing tests is scored with the partial pass_rate."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_app.py").write_text(
        "def test_ok(): assert True\n\ndef test_bad(): assert False\n"
    )

    assertion = SandboxAssertion(
        type="test_suite",
        target="python -m pytest -q .wb_bench/tests --junitxml=.wb_bench/results.xml",
        result_file=".wb_bench/results.xml",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions([assertion], executor, scores_out=scores)
    assert passed is False
    assert scores["pass_rate"] == 0.5
    assert scores["tests_passed"] == 1.0
    assert scores["tests_total"] == 2.0


@pytest.mark.asyncio
async def test_test_suite_json_reward_pass(executor, tmp_path):
    """A scorer writing a numeric reward.json passes at reward >= 1.0."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "scoring.py").write_text(
        "import json\njson.dump({'reward': 1.0}, open('.wb_bench/reward.json', 'w'))\n"
    )
    (tests_dir / "test.sh").write_text("#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n")

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions([assertion], executor, scores_out=scores)
    assert passed is True
    assert scores["pass_rate"] == 1.0


@pytest.mark.asyncio
async def test_test_suite_missing_result_file_fails(executor, tmp_path):
    """A command that produces no result file yields a clear failure."""
    assertion = SandboxAssertion(
        type="test_suite",
        target="echo nothing",
        result_file=".wb_bench/results.xml",
    )
    passed, details = await evaluate_sandbox_assertions([assertion], executor)
    assert passed is False
    assert "unreadable" in details


@pytest.mark.asyncio
async def test_test_suite_command_failure_without_result_file(executor, tmp_path):
    """A failing command with no result file falls back to exit-code verdict."""
    assertion = SandboxAssertion(
        type="test_suite",
        target="exit 3",
    )
    passed, details = await evaluate_sandbox_assertions([assertion], executor)
    assert passed is False
    assert "failed" in details


@pytest.mark.asyncio
async def test_test_suite_exit_code_success(executor):
    """A suite command that succeeds without a result file passes via exit code."""
    assertion = SandboxAssertion(
        type="test_suite",
        target="echo suite ok",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions([assertion], executor, scores_out=scores)
    assert passed is True
    assert scores["pass_rate"] == 1.0


@pytest.mark.asyncio
async def test_test_suite_json_reward_partial_fail(executor, tmp_path):
    """A scorer writing reward < 1.0 fails but keeps the numeric pass_rate."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "scoring.py").write_text(
        "import json\njson.dump({'reward': 0.5}, open('.wb_bench/reward.json', 'w'))\n"
    )
    (tests_dir / "test.sh").write_text("#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n")

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions([assertion], executor, scores_out=scores)
    assert passed is False
    assert scores["pass_rate"] == 0.5


@pytest.mark.asyncio
async def test_test_suite_json_reward_unreadable(executor):
    """A reward file that never appears yields a clear failure."""
    assertion = SandboxAssertion(
        type="test_suite",
        target="echo nothing",
        result_file=".wb_bench/reward.json",
    )
    passed, details = await evaluate_sandbox_assertions([assertion], executor)
    assert passed is False
    assert "unreadable" in details


@pytest.mark.asyncio
async def test_test_suite_json_reward_no_field(executor, tmp_path):
    """A reward file lacking a numeric reward field fails clearly."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "scoring.py").write_text(
        "import json\njson.dump({'message': 'ok'}, open('.wb_bench/reward.json', 'w'))\n"
    )
    (tests_dir / "test.sh").write_text("#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n")

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    passed, details = await evaluate_sandbox_assertions([assertion], executor)
    assert passed is False
    assert "no reward/pass_rate field" in details


@pytest.mark.asyncio
async def test_test_suite_junit_no_tests(executor, tmp_path):
    """A JUnit report declaring no tests fails clearly."""
    assertion = SandboxAssertion(
            type="test_suite",
            target="mkdir -p .wb_bench && echo '<testsuite tests=\"0\"/>' > .wb_bench/empty.xml",
            result_file=".wb_bench/empty.xml",
        )
    passed, details = await evaluate_sandbox_assertions([assertion], executor)
    assert passed is False
    assert "declares no tests" in details


def test_parse_reward_result_variants() -> None:
    """parse_reward_result handles bare numbers, score keys, and rejections."""
    from myrm_agent_harness.eval.suite_judge import parse_reward_result

    assert parse_reward_result("0.8") == 0.8
    assert parse_reward_result('{"score": 0.75}') == 0.75
    assert parse_reward_result('{"reward_score": 1}') == 1.0
    assert parse_reward_result('{"reward": true}') is None
    assert parse_reward_result('{"reward": "high"}') is None
    assert parse_reward_result("<xml>") is None
    assert parse_reward_result("") is None



def test_parse_junit_result_malformed() -> None:
    """Malformed or non-numeric JUnit attributes degrade to zero counts."""
    from myrm_agent_harness.eval.suite_judge import parse_junit_result

    assert parse_junit_result("<not-xml") == (0, 0)
    assert parse_junit_result("<testsuite tests='abc' failures='x'/>") == (0, 0)
    assert parse_junit_result("<testsuite tests='' />") == (0, 0)


def test_parse_junit_result_multi_suite() -> None:
    """Multiple testsuites under a testsuites root are aggregated."""
    from myrm_agent_harness.eval.suite_judge import parse_junit_result

    xml = (
        "<testsuites>"
        "<testsuite tests='3' failures='1' errors='0'/>"
        "<testsuite tests='2' failures='0' errors='1'/>"
        "</testsuites>"
    )
    assert parse_junit_result(xml) == (3, 5)


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

        passed, _ = evaluate_state_assertions(
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

        passed, _ = evaluate_state_assertions(
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

    os.environ.setdefault("MYRM_EVAL_JUDGE_MODEL", "gpt-4o-mini")

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


class TestToolAssertionBranches:
    """Edge branches of evaluate_tool_assertions."""

    def test_tool_name_from_dict(self):
        from myrm_agent_harness.eval.assertions import ToolAssertion, evaluate_tool_assertions

        passed, details = evaluate_tool_assertions(
            [{"name": "web_search", "args": {}}],
            ToolAssertion(expected_tools=["web_search"]),
        )
        assert passed is True
        assert "web_search" in details

    def test_tool_name_from_object(self):
        from myrm_agent_harness.eval.assertions import ToolAssertion, evaluate_tool_assertions

        class FakeTool:
            name = "code_exec"

        passed, _ = evaluate_tool_assertions(
            [FakeTool()],
            ToolAssertion(expected_tools=["code_exec"]),
        )
        assert passed is True

    def test_require_all_missing_tool(self):
        from myrm_agent_harness.eval.assertions import ToolAssertion, evaluate_tool_assertions

        passed, details = evaluate_tool_assertions(
            ["web_search"],
            ToolAssertion(expected_tools=["web_search", "code_exec"], require_all=True),
        )
        assert passed is False
        assert "Missing tools" in details


class TestSandboxAssertionBranches:
    """Edge branches of evaluate_sandbox_assertions."""

    @pytest.mark.asyncio
    async def test_json_matches_missing_file(self, executor):
        passed, details = await evaluate_sandbox_assertions(
            [SandboxAssertion(type="json_matches", target="nope.json", expected="a=1")],
            executor,
        )
        assert passed is False
        assert "does not exist" in details

    @pytest.mark.asyncio
    async def test_unknown_assertion_type(self, executor):
        passed, details = await evaluate_sandbox_assertions(
            [SandboxAssertion(type="bogus_type", target="x")],
            executor,
        )
        assert passed is False
        assert "Unknown assertion type" in details


class TestStateAssertionBranches:
    """Edge branches of evaluate_state_assertions."""

    def test_json_schema_output_not_json(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected='{"required": ["name"]}')],
            "not json at all",
        )
        assert passed is False
        assert "json_schema requires valid JSON" in details

    def test_json_schema_invalid_schema(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="json_schema", expected="not-a-json-schema")],
            '{"name": "Alice"}',
        )
        assert passed is False
        assert "invalid JSON schema definition" in details

    def test_jaccard_similarity_below_threshold(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, details = evaluate_state_assertions(
            [StateAssertion(type="jaccard_similarity", expected="completely unrelated topic words", threshold=0.9)],
            "hello world",
        )
        assert passed is False
        assert "below threshold" in details

    def test_jaccard_similarity_pass(self):
        from myrm_agent_harness.eval.assertions import evaluate_state_assertions
        from myrm_agent_harness.eval.protocols import StateAssertion

        passed, _ = evaluate_state_assertions(
            [StateAssertion(type="jaccard_similarity", expected="hello world", threshold=0.5)],
            "hello world again",
        )
        assert passed is True

    def test_schema_must_be_object(self):
        from myrm_agent_harness.eval.assertions import _validate_json_schema

        assert _validate_json_schema({"a": 1}, "not-a-dict") == "Schema must be a JSON object"  # type: ignore[arg-type]
        assert _validate_json_schema({"a": 1}, {"required": ["a"]}) is None

    def test_check_json_type_unknown(self):
        from myrm_agent_harness.eval.assertions import _check_json_type

        assert _check_json_type("x", "unknown_type") is True


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
        sent_prompt = litellm_mock.acompletion.await_args.kwargs["messages"][0]["content"]
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
        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice", threshold=0.7)]
        passed, _ = await evaluate_semantic_assertions(assertions, "output")
        assert passed is True

    @pytest.mark.asyncio
    async def test_scoring_unparseable_fails_via_fail_prefix(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, "FAIL: not nice")
        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice", threshold=0.7)]
        passed, details = await evaluate_semantic_assertions(assertions, "output")
        assert passed is False
        assert "score 0.00 < threshold" in details

    @pytest.mark.asyncio
    async def test_scoring_unparseable_totally(self, monkeypatch):
        from myrm_agent_harness.eval.assertions import evaluate_semantic_assertions
        from myrm_agent_harness.eval.protocols import SemanticAssertion

        self._mock_litellm(monkeypatch, "definitely not a number")
        assertions = [SemanticAssertion(type="llm_judge", expected="Be nice", threshold=0.7)]
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
