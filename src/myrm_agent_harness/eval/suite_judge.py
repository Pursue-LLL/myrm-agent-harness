"""Task-Native Test Suite Judge (Rule).

[INPUT]
- protocol::SandboxAssertion (type=test_suite with target command + result_file)
- code_execution CodeExecutor (sandbox execution/read primitives)

[OUTPUT]
- TestSuiteResult: numeric suite verdict (pass_rate, tests_passed/tests_total)
- evaluate_test_suite_assertion(): run the suite command and derive a verdict
- parse_junit_result(): JUnit XML -> (passed, total), skipped excluded
- parse_reward_result(): reward payload (bare numeric text or JSON) -> reward/pass_rate float
- _read_reward_payload(): reward file reader with sibling candidate fallback

[POS]
Run each task's native test suite inside the sandbox (pytest, custom scorer)
and extract a numeric pass_rate so partial success is not flattened into a
binary pass/fail. Shared by the eval sandbox assertions (Rule judge) for
Code/Office/Security tracks.

The target command may contain the ``{workspace}`` placeholder (expanded to
the executor's live workspace path) and ``SandboxAssertion.readonly_paths``
mounts external grading assets read-only for the grader command.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.eval.protocols import SandboxAssertion
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionResult,
    )


@dataclass(frozen=True, slots=True)
class TestSuiteResult:
    """Outcome of running a task-native test suite (Rule judge).

    Carries the numeric pass_rate so partial success (e.g. 62/80 tests) is not
    flattened to a binary pass/fail. ``details`` is a human-readable summary.
    """

    passed: bool
    pass_rate: float
    tests_passed: int
    tests_total: int
    details: str


def parse_junit_result(xml_text: str) -> tuple[int, int]:
    """Parse JUnit XML into (tests_passed, tests_total).

    Aggregates across all ``<testsuite>`` elements (a ``<testsuites>`` root is
    flattened); malformed or non-numeric attributes are treated as 0. Skipped
    tests are excluded from the pass count (pass = total - failures - errors -
    skipped).
    """
    try:
        # Python 3.13+ ElementTree disables entity expansion and external
        # entities (billion-laughs protection); sandbox JUnit reports are still
        # treated as untrusted input and only the tests/failures/errors/skipped
        # attributes are read.
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError:
        return 0, 0

    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")

    def _int(value: str | None, default: int = 0) -> int:
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    total = sum(_int(s.attrib.get("tests")) for s in suites)
    if total <= 0:
        return 0, 0
    failed = sum(_int(s.attrib.get("failures")) for s in suites)
    errors = sum(_int(s.attrib.get("errors")) for s in suites)
    skipped = sum(_int(s.attrib.get("skipped")) for s in suites)
    passed = max(0, total - failed - errors - skipped)
    return passed, total


# Field lookup order matches the official WBBench reward payload reader
# (``judge/runners/rule/reward_payload.py::score_from_payload``), which checks
# ``reward`` → ``overall`` → ``test_pass_rate`` → ``score``. The trailing
# ``pass_rate``/``reward_score`` keys are kept for backward compatibility with
# Myrm-authored reward files that used the earlier spelling.
_REWARD_KEYS: tuple[str, ...] = (
    "reward",
    "overall",
    "test_pass_rate",
    "score",
    "pass_rate",
    "reward_score",
)

# File-name candidates probed when a declared reward file is missing, in the
# official probe order (``payload_candidate_paths``) plus the Code
# ``script_verifier`` spelling that writes a bare numeric ``reward.txt``.
_REWARD_CANDIDATE_NAMES: tuple[str, ...] = ("score.json", "reward.json", "reward.txt")


def parse_reward_result(text: str) -> float | None:
    """Parse a reward/pass_rate/score value out of a result payload.

    Accepts a bare numeric document (``script_verifier`` writes
    ``str(reward["overall"])`` into reward.txt) or a JSON payload. For JSON,
    prefers the official WBBench keys (reward/overall/test_pass_rate/score);
    falls back to a plain numeric JSON document. Returns None when nothing
    numeric is present.
    """
    stripped = text.strip()
    try:
        return float(stripped)
    except ValueError:
        pass
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        for key in _REWARD_KEYS:
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return float(data)
    return None


def _suite_failure(details: str) -> TestSuiteResult:
    return TestSuiteResult(
        passed=False,
        pass_rate=0.0,
        tests_passed=0,
        tests_total=0,
        details=details,
    )


# Bounded tail of a failed suite command's output. A timeout/crash carries only a
# bare ``error`` (e.g. "Timeout"), so the last lines the grader printed are
# appended to the failure detail to make the stuck point locatable.
_OUTPUT_TAIL_CHARS = 800


def _output_tail(result: ExecutionResult) -> str:
    """Bounded tail of the suite command's stdout (stderr merges into stdout)."""
    tail = result.stdout.strip()
    if len(tail) > _OUTPUT_TAIL_CHARS:
        return f"... (truncated {len(tail) - _OUTPUT_TAIL_CHARS} chars) {tail[-_OUTPUT_TAIL_CHARS:]}"
    return tail


def _with_output_tail(detail: str, result: ExecutionResult) -> str:
    """Append the command output tail to a failure detail when it adds context."""
    tail = _output_tail(result)
    if tail and tail not in detail:
        return f"{detail} | last output: {tail}"
    return detail


def _command_failure_detail(result: ExecutionResult) -> str:
    return _with_output_tail(result.error or result.stderr or "non-zero exit", result)


def _counts_from_reward(text: str) -> tuple[int, int] | None:
    """Extract (passed, total) from a counts-only reward payload.

    Matches the official ``counts_from_payload`` (``judge/runners/rule/
    reward_payload.py``): reads ``tests_passed``/``tests_total`` integers,
    falling back to a ``tests`` array of per-check entries carrying a ``passed``
    flag.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    def _int(value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "pass", "passed"}
        return bool(value)

    passed = _int(data.get("tests_passed"))
    total = _int(data.get("tests_total"))
    tests = data.get("tests")
    if (passed is None or total is None) and isinstance(tests, list):
        entries = [entry for entry in tests if isinstance(entry, dict)]
        passed = sum(1 for entry in entries if _bool(entry.get("passed")))
        total = len(entries)
    if passed is None and total is None:
        return None
    passed = 0 if passed is None or passed < 0 else passed
    total = 0 if total is None or total < 0 else total
    if passed > total:
        passed = total
    return passed, total


async def _read_reward_payload(
    target: str,
    executor: CodeExecutor,
) -> tuple[str | None, str]:
    """Read a scorable reward payload, trying the declared path then alternates.

    The official WBBench reward reader probes ``score.json`` then ``reward.json``
    in the verifier dir (``judge/runners/rule/reward_payload.py``) and **skips a
    candidate whose content is not scorable**, continuing to the next sibling
    (``payload_is_scorable``). The Code ``script_verifier`` family writes a bare
    numeric ``reward.txt``. The declared ``result_file`` usually pins one of
    those names, but a task-native scorer may write another spelling, so a
    missing or unscorable declared file falls back to its siblings. Returns
    ``(raw_text, resolved_path)``; ``raw_text`` is None when no candidate is
    readable, and holds the first readable-but-unscorable payload when one
    exists so the caller can report why scoring failed.
    """
    directory, name = target.rsplit("/", 1) if "/" in target else ("", target)
    candidates = [target]
    candidates.extend(f"{directory}/{alt}" if directory else alt for alt in _REWARD_CANDIDATE_NAMES if alt != name)
    first_readable: tuple[str, str] | None = None
    for candidate in candidates:
        try:
            raw = await executor.read_file(candidate)
        except Exception:
            continue
        if parse_reward_result(raw) is not None or _counts_from_reward(raw) is not None:
            return raw, candidate
        if first_readable is None:
            first_readable = (raw, candidate)
    if first_readable is not None:
        return first_readable
    return None, target


async def evaluate_test_suite_assertion(
    assertion: SandboxAssertion,
    executor: CodeExecutor,
) -> TestSuiteResult:
    """Run a task-native test suite command and derive a numeric verdict.

    ``assertion.target`` may reference the live agent workspace via the
    ``{workspace}`` placeholder, and ``assertion.readonly_paths`` mounts
    external grading assets read-only for the grader command.

    Supports two result formats resolved from ``assertion.result_file``:
    - ends with ``.xml``: parsed as JUnit XML (pytest --junitxml).
    - ends with ``.json``/``.txt``: parsed as a numeric reward payload (JSON
      dict or bare numeric text such as the Code ``script_verifier`` reward.txt).
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import (
        ExecutionContext,
    )

    # Resolve the live agent workspace. The command may reference external
    # grading assets via ``{workspace}`` (expanded here) plus
    # ``assertion.readonly_paths`` (read-only mounts outside the workspace).
    # WBBench's verifier default is 600s; large task suites routinely exceed
    # the 60s ExecutionContext default, so test_suite defaults to 600s and
    # stays overridable per-assertion via ``SandboxAssertion.timeout``.
    workspace = executor.workspace_path
    timeout = assertion.timeout or 600
    ctx = ExecutionContext(
        code=assertion.target.replace("{workspace}", workspace),
        timeout=timeout,
        work_dir=workspace,
        additional_readonly_paths=assertion.readonly_paths,
    )
    result = await executor.execute_bash(ctx)

    target = (assertion.result_file or "").strip().replace("{workspace}", workspace)

    # pytest exits non-zero when tests fail, but still writes a valid JUnit
    # report — so only a hard execution error (timeout, crash, security block)
    # aborts before reading the result file, which is then unreliable.
    if result.error:
        return _suite_failure(f"Test suite command failed: {_command_failure_detail(result)}")

    if target.endswith((".json", ".txt")):
        raw, target = await _read_reward_payload(target, executor)
        if raw is None:
            return _suite_failure(_with_output_tail(f"Reward file '{target}' unreadable", result))
        reward = parse_reward_result(raw)
        if reward is not None:
            passed = reward >= 1.0
            return TestSuiteResult(
                passed=passed,
                pass_rate=max(0.0, min(1.0, reward)),
                tests_passed=1 if passed else 0,
                tests_total=1,
                details=f"Reward {reward:.3f} ({'PASS' if passed else 'FAIL'})",
            )
        # Counts-only payloads (official fallback): a scorer may write only
        # ``tests_passed``/``tests_total`` (or ``tests[]``) without an aggregate
        # reward, and the official reader derives the pass_rate from them.
        counts = _counts_from_reward(raw)
        if counts is not None:
            tests_passed, tests_total = counts
            if tests_total <= 0:
                return _suite_failure(f"Reward file '{target}' declares no tests")
            pass_rate = round(tests_passed / tests_total, 4)
            passed = tests_passed == tests_total
            return TestSuiteResult(
                passed=passed,
                pass_rate=pass_rate,
                tests_passed=tests_passed,
                tests_total=tests_total,
                details=f"{tests_passed}/{tests_total} tests passed",
            )
        return _suite_failure(f"Reward file '{target}' contains no reward/pass_rate field")

    # Default: JUnit XML.
    if target.endswith(".xml"):
        try:
            raw = await executor.read_file(target)
        except Exception as exc:
            return _suite_failure(_with_output_tail(f"JUnit file '{target}' unreadable: {exc}", result))
        tests_passed, tests_total = parse_junit_result(raw)
        if tests_total <= 0:
            return _suite_failure(f"JUnit file '{target}' declares no tests")
        pass_rate = round(tests_passed / tests_total, 4)
        passed = tests_passed == tests_total
        return TestSuiteResult(
            passed=passed,
            pass_rate=pass_rate,
            tests_passed=tests_passed,
            tests_total=tests_total,
            details=f"{tests_passed}/{tests_total} tests passed",
        )

    # No explicit result file: fall back to command exit success (cmd_success).
    if result.success is False:
        return _suite_failure(f"Test suite command failed: {_command_failure_detail(result)}")
    return TestSuiteResult(
        passed=True,
        pass_rate=1.0,
        tests_passed=1,
        tests_total=1,
        details="Test suite command exited successfully",
    )
