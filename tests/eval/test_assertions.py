"""Tests for the Eval assertion engine — sandbox (file/command/json), tool branches, and suite grading assets."""

import json

import pytest

from myrm_agent_harness.eval.assertions import evaluate_sandbox_assertions
from myrm_agent_harness.eval.protocols import SandboxAssertion


@pytest.mark.asyncio
async def test_evaluate_sandbox_assertions_empty(executor):
    passed, details = await evaluate_sandbox_assertions([], executor)
    assert passed is None
    assert details is None


@pytest.mark.asyncio
async def test_evaluate_sandbox_assertions_no_executor():
    passed, details = await evaluate_sandbox_assertions(
        [SandboxAssertion(type="file_exists", target="test.txt")], None
    )
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
        [SandboxAssertion(type="file_exists", target=str(tmp_path / "missing.txt"))],
        executor,
    )
    assert passed is False
    assert "does not exist" in details

    # Test file_not_exists success
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="file_not_exists", target=str(tmp_path / "missing.txt")
            )
        ],
        executor,
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
        [
            SandboxAssertion(
                type="file_contains", target=str(test_file), expected="world"
            )
        ],
        executor,
    )
    assert passed is True

    # Test failure (wrong content)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="file_contains", target=str(test_file), expected="python"
            )
        ],
        executor,
    )
    assert passed is False
    assert "does not contain" in details

    # Test failure (file missing)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="file_contains",
                target=str(tmp_path / "missing.txt"),
                expected="world",
            )
        ],
        executor,
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
        [
            SandboxAssertion(
                type="cmd_output_contains", target="echo hello world", expected="world"
            )
        ],
        executor,
    )
    assert passed is True

    # Test failure (wrong output)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="cmd_output_contains", target="echo hello world", expected="python"
            )
        ],
        executor,
    )
    assert passed is False
    assert "does not contain" in details

    # Test failure (command fails)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="cmd_output_contains", target="exit 1", expected="python"
            )
        ],
        executor,
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
        [
            SandboxAssertion(
                type="json_matches", target=str(test_file), expected="name=myrm"
            )
        ],
        executor,
    )
    assert passed is True

    # Test success (nested key)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="json_matches",
                target=str(test_file),
                expected="config.version=1.0",
            )
        ],
        executor,
    )
    assert passed is True

    # Test success (boolean value converted to string)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="json_matches",
                target=str(test_file),
                expected="config.enabled=True",
            )
        ],
        executor,
    )
    assert passed is True

    # Test failure (wrong value)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="json_matches", target=str(test_file), expected="name=wrong"
            )
        ],
        executor,
    )
    assert passed is False
    assert "expected 'wrong'" in details

    # Test failure (missing key)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="json_matches", target=str(test_file), expected="missing=value"
            )
        ],
        executor,
    )
    assert passed is False
    assert "not found" in details

    # Test failure (invalid format)
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="json_matches", target=str(test_file), expected="invalid_format"
            )
        ],
        executor,
    )
    assert passed is False
    assert "Invalid expected format" in details

    # Test failure (invalid JSON)
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{bad json")
    passed, details = await evaluate_sandbox_assertions(
        [
            SandboxAssertion(
                type="json_matches", target=str(bad_file), expected="name=myrm"
            )
        ],
        executor,
    )
    assert passed is False
    assert "not valid JSON" in details


class TestToolAssertionBranches:
    """Edge branches of evaluate_tool_assertions."""

    def test_tool_name_from_dict(self):
        from myrm_agent_harness.eval.assertions import (
            ToolAssertion,
            evaluate_tool_assertions,
        )

        passed, details = evaluate_tool_assertions(
            [{"name": "web_search", "args": {}}],
            ToolAssertion(expected_tools=["web_search"]),
        )
        assert passed is True
        assert "web_search" in details

    def test_tool_name_from_object(self):
        from myrm_agent_harness.eval.assertions import (
            ToolAssertion,
            evaluate_tool_assertions,
        )

        class FakeTool:
            name = "code_exec"

        passed, _ = evaluate_tool_assertions(
            [FakeTool()],
            ToolAssertion(expected_tools=["code_exec"]),
        )
        assert passed is True

    def test_require_all_missing_tool(self):
        from myrm_agent_harness.eval.assertions import (
            ToolAssertion,
            evaluate_tool_assertions,
        )

        passed, details = evaluate_tool_assertions(
            ["web_search"],
            ToolAssertion(expected_tools=["web_search", "code_exec"], require_all=True),
        )
        assert passed is False
        assert "Missing tools" in details


class TestTestSuiteGradingAssets:
    """test_suite grading via {workspace} placeholder + readonly_paths mounts."""

    @pytest.mark.asyncio
    async def test_workspace_placeholder_with_readonly_mount(self, executor, tmp_path):
        """A verifier living outside the workspace runs via readonly_paths and the
        {workspace} placeholder, writing reward.json inside the workspace."""
        ws = tmp_path / "ws"
        ws.mkdir()
        graders = tmp_path / "graders"
        graders.mkdir()
        (graders / "verifier.py").write_text(
            "import json, os\nfrom pathlib import Path\n"
            "ws = Path(os.environ['WORKSPACE'])\n"
            "reward = 1.0 if (ws / 'solution.py').exists() else 0.0\n"
            "(ws / 'reward.json').write_text(json.dumps({'reward': reward}))\n"
        )
        (ws / "solution.py").write_text("x = 1\n")

        ex = executor
        ex.bind_workspace(str(ws))
        assertion = SandboxAssertion(
            type="test_suite",
            target=f"WORKSPACE={{workspace}} python3 {graders / 'verifier.py'}",
            result_file="{workspace}/reward.json",
            readonly_paths=(str(graders),),
        )
        scores: dict[str, float] = {}
        passed, _ = await evaluate_sandbox_assertions(
            [assertion], ex, scores_out=scores
        )
        assert passed is True
        assert scores["pass_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_external_grader_blocked_without_readonly_mount(
        self, executor, tmp_path
    ):
        """Without readonly_paths the workspace-external grader path is blocked."""
        ws = tmp_path / "ws"
        ws.mkdir()
        graders = tmp_path / "graders"
        graders.mkdir()
        (graders / "verifier.py").write_text("print('nope')\n")

        ex = executor
        ex.bind_workspace(str(ws))
        assertion = SandboxAssertion(
            type="test_suite",
            target=f"python3 {graders / 'verifier.py'}",
        )
        passed, details = await evaluate_sandbox_assertions([assertion], ex)
        assert passed is False
        assert "blocked" in details

    @pytest.mark.asyncio
    async def test_failed_grader_reports_low_reward(self, executor, tmp_path):
        """A verifier grading against a missing solution yields a low reward."""
        ws = tmp_path / "ws"
        ws.mkdir()
        graders = tmp_path / "graders"
        graders.mkdir()
        (graders / "verifier.py").write_text(
            "import json, os\nfrom pathlib import Path\n"
            "ws = Path(os.environ['WORKSPACE'])\n"
            "reward = 1.0 if (ws / 'solution.py').exists() else 0.25\n"
            "(ws / 'reward.json').write_text(json.dumps({'reward': reward}))\n"
        )

        ex = executor
        ex.bind_workspace(str(ws))
        assertion = SandboxAssertion(
            type="test_suite",
            target=f"WORKSPACE={{workspace}} python3 {graders / 'verifier.py'}",
            result_file="{workspace}/reward.json",
            readonly_paths=(str(graders),),
        )
        scores: dict[str, float] = {}
        passed, _ = await evaluate_sandbox_assertions(
            [assertion], ex, scores_out=scores
        )
        assert passed is False
        assert scores["pass_rate"] == 0.25


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
