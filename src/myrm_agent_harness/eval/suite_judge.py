"""Task-Native Test Suite Judge (Rule).

[INPUT]
- protocol::SandboxAssertion (type=test_suite with target command + result_file)
- code_execution CodeExecutor (sandbox execution/read primitives)

[OUTPUT]
- TestSuiteResult: numeric suite verdict (pass_rate, tests_passed/tests_total)
- evaluate_test_suite_assertion(): run the suite command and derive a verdict
- parse_junit_result(): JUnit XML -> (passed, total), skipped excluded
- parse_reward_result(): JSON reward payload -> reward/pass_rate float

[POS]
Run each task's native test suite inside the sandbox (pytest, custom scorer)
and extract a numeric pass_rate so partial success is not flattened into a
binary pass/fail. Shared by the eval sandbox assertions (Rule judge) for
Code/Office/Security tracks.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.eval.protocols import SandboxAssertion
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor


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
        # Python 3.13+ ElementTree 默认禁止 entity expansion 与外部实体（billion-laughs 防护），
        # 沙箱内 JUnit 报告视为不可信输入，仍只读取 tests/failures/errors/skipped 属性。
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


def parse_reward_result(text: str) -> float | None:
    """Parse a reward/pass_rate/score field out of a JSON result payload.

    Prefers an explicit ``reward`` or ``pass_rate`` key; falls back to a plain
    numeric JSON document. Returns None when nothing numeric is present.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        for key in ("reward", "pass_rate", "score", "reward_score"):
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


async def evaluate_test_suite_assertion(
    assertion: SandboxAssertion,
    executor: CodeExecutor,
) -> TestSuiteResult:
    """Run a task-native test suite command and derive a numeric verdict.

    Supports two result formats resolved from ``assertion.result_file``:
    - ends with ``.xml``: parsed as JUnit XML (pytest --junitxml).
    - ends with ``.json``: parsed as a JSON reward payload.
    """
    from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext

    # WBBench's verifier default is 600s; large task suites routinely exceed the
    # 60s ExecutionContext default, so test_suite commands default to 600s and
    # stay overridable per-assertion via ``SandboxAssertion.timeout``.
    timeout = assertion.timeout or 600
    ctx = ExecutionContext(code=assertion.target, timeout=timeout)
    result = await executor.execute_bash(ctx)

    target = (assertion.result_file or "").strip()

    # pytest exits non-zero when tests fail, but still writes a valid JUnit
    # report — so only a hard execution error (timeout, crash, security block)
    # aborts before reading the result file.
    if result.error and not target:
        return _suite_failure(f"Test suite command failed: {result.error or result.stderr or 'non-zero exit'}")

    if target.endswith(".json"):
        try:
            raw = await executor.read_file(target)
        except Exception as exc:
            return _suite_failure(f"Reward file '{target}' unreadable: {exc}")
        reward = parse_reward_result(raw)
        if reward is None:
            return _suite_failure(f"Reward file '{target}' contains no reward/pass_rate field")
        passed = reward >= 1.0
        return TestSuiteResult(
            passed=passed,
            pass_rate=max(0.0, min(1.0, reward)),
            tests_passed=1 if passed else 0,
            tests_total=1,
            details=f"Reward {reward:.3f} ({'PASS' if passed else 'FAIL'})",
        )

    # Default: JUnit XML.
    if target.endswith(".xml"):
        try:
            raw = await executor.read_file(target)
        except Exception as exc:
            return _suite_failure(f"JUnit file '{target}' unreadable: {exc}")
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
        return _suite_failure(f"Test suite command failed: {result.error or result.stderr or 'non-zero exit'}")
    return TestSuiteResult(
        passed=True,
        pass_rate=1.0,
        tests_passed=1,
        tests_total=1,
        details="Test suite command exited successfully",
    )
