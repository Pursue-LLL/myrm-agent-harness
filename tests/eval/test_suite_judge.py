"""Tests for the task-native test suite judge (suite_judge)."""

import pytest

from myrm_agent_harness.eval.assertions import evaluate_sandbox_assertions
from myrm_agent_harness.eval.protocols import SandboxAssertion


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
    passed, _ = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
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
    passed, _ = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
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
    (tests_dir / "test.sh").write_text(
        "#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n"
    )

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
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
async def test_test_suite_command_blocked_reports_block_error():
    """A security-blocked command reports the block, not a result-file error.

    The command never ran (permission_denied), so any declared result file is
    unreliable; the failure must surface the block reason instead of a
    misleading ``unreadable`` message.
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionResult,
    )

    class _BlockedExecutor:
        workspace_path = "/tmp/wb_bench_blocked_ws"

        async def execute_bash(self, ctx):
            return ExecutionResult(
                success=False,
                error="Command blocked for security reasons: ${} variable expansion",
                error_category="permission_denied",
                stderr="[blocked]",
            )

        async def read_file(self, path):
            raise FileNotFoundError(path)

    assertion = SandboxAssertion(
        type="test_suite",
        target="WORKSPACE={workspace} python3 verifier.py",
        result_file="{workspace}/.wb_bench/logs/reward.txt",
    )
    passed, details = await evaluate_sandbox_assertions(
        [assertion], _BlockedExecutor()
    )
    assert passed is False
    assert "blocked" in details
    assert "unreadable" not in details


@pytest.mark.asyncio
async def test_test_suite_timeout_includes_output_tail():
    """A timed-out suite surfaces the last lines it printed, not just 'Timeout'.

    A timeout carries only the bare ``error`` text, which does not say where the
    grader got stuck; the failure detail must append the command output tail.
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionResult,
    )

    class _TimeoutExecutor:
        workspace_path = "/tmp/wb_bench_timeout_ws"

        async def execute_bash(self, ctx):
            return ExecutionResult(
                success=False,
                error="Timeout",
                error_category="timeout",
                stdout=(
                    "collecting...\n"
                    "tests/grading/test_calc.py::test_divide ...\n"
                    "FAILED tests/grading/test_calc.py::test_divide - KeyboardInterrupt"
                ),
            )

        async def read_file(self, path):
            raise FileNotFoundError(path)

    assertion = SandboxAssertion(
        type="test_suite",
        target="WORKSPACE={workspace} python3 verifier.py",
        result_file="{workspace}/.wb_bench/logs/reward.txt",
    )
    passed, details = await evaluate_sandbox_assertions(
        [assertion], _TimeoutExecutor()
    )
    assert passed is False
    assert "Timeout" in details
    assert "test_divide" in details
    assert "unreadable" not in details


@pytest.mark.asyncio
async def test_test_suite_nonzero_exit_without_result_file_includes_tail():
    """A non-zero exit without a result file reports the printed output tail.

    The persistent session merges stderr into stdout and reports only
    ``non-zero exit``, so the locatable traceback lives in stdout and must be
    surfaced.
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionResult,
    )

    class _CrashExecutor:
        workspace_path = "/tmp/wb_bench_crash_ws"

        async def execute_bash(self, ctx):
            return ExecutionResult(
                success=False,
                exit_code=1,
                stdout=(
                    'Traceback (most recent call last):\n'
                    '  File "scoring.py", line 12, in <module>\n'
                    "ValueError: unexpected reward shape"
                ),
            )

        async def read_file(self, path):
            raise FileNotFoundError(path)

    assertion = SandboxAssertion(
        type="test_suite",
        target="cd {workspace} && python3 scoring.py",
    )
    passed, details = await evaluate_sandbox_assertions(
        [assertion], _CrashExecutor()
    )
    assert passed is False
    assert "non-zero exit" in details
    assert "ValueError: unexpected reward shape" in details


@pytest.mark.asyncio
async def test_test_suite_junit_unreadable_includes_output_tail():
    """A missing JUnit report (e.g. pytest collection crash) surfaces its cause.

    pytest aborts before writing the XML when collection fails (missing
    dependency / ImportError in conftest), so the declared result file is
    unreadable; the failure must expose the collection error from stdout.
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionResult,
    )

    class _CollectCrashExecutor:
        workspace_path = "/tmp/wb_bench_collect_crash_ws"

        async def execute_bash(self, ctx):
            return ExecutionResult(
                success=False,
                exit_code=4,
                stdout=(
                    "ImportError while loading conftest '/tmp/wb_bench/.../conftest.py'.\n"
                    "ModuleNotFoundError: No module named 'xlrd'"
                ),
            )

        async def read_file(self, path):
            raise FileNotFoundError(path)

    assertion = SandboxAssertion(
        type="test_suite",
        target="cd {workspace} && python3 -m pytest --junitxml=results.xml",
        result_file="{workspace}/results.xml",
    )
    passed, details = await evaluate_sandbox_assertions(
        [assertion], _CollectCrashExecutor()
    )
    assert passed is False
    assert "unreadable" in details
    assert "No module named 'xlrd'" in details


@pytest.mark.asyncio
async def test_test_suite_reward_unreadable_includes_output_tail():
    """A scorer that crashes before writing reward.json exposes its traceback."""
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionResult,
    )

    class _ScorerCrashExecutor:
        workspace_path = "/tmp/wb_bench_scorer_crash_ws"

        async def execute_bash(self, ctx):
            return ExecutionResult(
                success=False,
                exit_code=1,
                stdout=(
                    'Traceback (most recent call last):\n'
                    '  File "tests/scoring.py", line 20, in <module>\n'
                    "KeyError: 'tests_total'"
                ),
            )

        async def read_file(self, path):
            raise FileNotFoundError(path)

    assertion = SandboxAssertion(
        type="test_suite",
        target="cd {workspace} && python3 tests/scoring.py",
        result_file="{workspace}/reward.json",
    )
    passed, details = await evaluate_sandbox_assertions(
        [assertion], _ScorerCrashExecutor()
    )
    assert passed is False
    assert "unreadable" in details
    assert "KeyError: 'tests_total'" in details


@pytest.mark.asyncio
async def test_test_suite_exit_code_success(executor):
    """A suite command that succeeds without a result file passes via exit code."""
    assertion = SandboxAssertion(
        type="test_suite",
        target="echo suite ok",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
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
    (tests_dir / "test.sh").write_text(
        "#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n"
    )

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
    assert passed is False
    assert scores["pass_rate"] == 0.5


@pytest.mark.asyncio
async def test_test_suite_counts_only_reward_scored(executor, tmp_path):
    """A counts-only reward payload is scored via tests_passed/tests_total."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "scoring.py").write_text(
        "import json\n"
        "json.dump({'tests_passed': 8, 'tests_total': 10}, "
        "open('.wb_bench/reward.json', 'w'))\n"
    )
    (tests_dir / "test.sh").write_text(
        "#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n"
    )

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    scores: dict[str, float] = {}
    passed, details = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
    assert passed is False
    assert scores["pass_rate"] == 0.8
    assert scores["tests_total"] == 10.0
    assert "8/10 tests passed" in details


@pytest.mark.asyncio
async def test_test_suite_reward_score_precedes_counts(executor, tmp_path):
    """An aggregate reward field wins over tests_passed/tests_total."""
    tests_dir = tmp_path / ".wb_bench" / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "scoring.py").write_text(
        "import json\n"
        "json.dump({'reward': 0.9, 'tests_passed': 3, 'tests_total': 10}, "
        "open('.wb_bench/reward.json', 'w'))\n"
    )
    (tests_dir / "test.sh").write_text(
        "#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n"
    )

    assertion = SandboxAssertion(
        type="test_suite",
        target="bash .wb_bench/tests/test.sh",
        result_file=".wb_bench/reward.json",
    )
    scores: dict[str, float] = {}
    passed, _ = await evaluate_sandbox_assertions(
        [assertion], executor, scores_out=scores
    )
    assert passed is False
    assert scores["pass_rate"] == 0.9


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
    (tests_dir / "test.sh").write_text(
        "#!/usr/bin/env bash\npython3 .wb_bench/tests/scoring.py\n"
    )

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

