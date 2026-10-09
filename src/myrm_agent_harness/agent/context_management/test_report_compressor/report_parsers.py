"""Parsers for JUnit XML, pytest-json, and Jest JSON test report wire formats.

[INPUT]
- report_compressor_types: NormalizedTestReport, TestFailureItem,
  TestReportCompressorConfig, TestReportFormatKind.

[OUTPUT]
- JUnitXmlParser, PytestJsonParser, JestJsonParser, StackFrameTrimmer,
  and parse_test_report_payload.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.test_report_compressor
- Module: report_parsers.py
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Sequence, Tuple

from myrm_agent_harness.agent.context_management.test_report_compressor.report_compressor_types import (
    NormalizedTestReport,
    TestFailureItem,
    TestReportCompressorConfig,
    TestReportFormatKind,
)

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class StackFrameTrimmer:
    """Intelligently compacts verbose stack traces by keeping head and tail frames."""

    @staticmethod
    def trim_stack(
        frames: Sequence[str],
        config: TestReportCompressorConfig,
    ) -> Tuple[str, ...]:
        """Cleans and truncates a sequence of raw stack trace lines."""
        clean: List[str] = []
        for frame in frames:
            line = frame.strip()
            if not line:
                continue
            if (
                line.startswith("at ")
                or ".py:" in line
                or ".java:" in line
                or ".js:" in line
                or ".ts:" in line
                or ".go:" in line
                or ".rb:" in line
                or line.startswith("File ")
            ):
                clean.append(line)

        if len(clean) < config.min_stack_frames_to_trim:
            return tuple(clean)

        head = clean[: config.keep_stack_head_frames]
        tail = clean[-config.keep_stack_tail_frames :]
        omitted = len(clean) - config.keep_stack_head_frames - config.keep_stack_tail_frames

        result = list(head)
        result.append(f"... ({omitted} frames omitted)")
        result.extend(tail)
        return tuple(result)


class JUnitXmlParser:
    """Parses JUnit standard XML test execution reports."""

    @staticmethod
    def parse(
        payload: str,
        config: TestReportCompressorConfig,
    ) -> Optional[NormalizedTestReport]:
        """Parses JUnit XML string into NormalizedTestReport."""
        sanitized = _ANSI_ESCAPE_RE.sub("", payload).strip()
        try:
            root = ET.fromstring(sanitized)
        except ET.ParseError:
            return None

        suites: List[ET.Element] = []
        tag = root.tag.lower()
        if tag == "testsuites":
            suites.extend(root.findall(".//testsuite"))
        elif tag == "testsuite":
            suites.append(root)
        else:
            found = root.findall(".//testsuite")
            if found:
                suites.extend(found)
            else:
                return None

        passed = 0
        failed = 0
        errors = 0
        skipped = 0
        duration = 0.0
        failures_list: List[TestFailureItem] = []

        for suite in suites:
            time_val = suite.attrib.get("time")
            if time_val:
                try:
                    duration += float(time_val)
                except ValueError:
                    pass

            for tc in suite.findall("testcase"):
                name = tc.attrib.get("name", "unnamed_test")
                classname = tc.attrib.get("classname", "")
                full_name = f"{classname}::{name}" if classname and classname != name else name

                failure_elem = tc.find("failure")
                error_elem = tc.find("error")
                skipped_elem = tc.find("skipped")

                if failure_elem is not None:
                    failed += 1
                    msg = failure_elem.attrib.get("message") or (failure_elem.text or "").strip()
                    stack_raw = (failure_elem.text or "").splitlines()
                    trimmed_stack = StackFrameTrimmer.trim_stack(stack_raw, config)
                    failures_list.append(
                        TestFailureItem(
                            name=full_name,
                            message=msg,
                            failure_type="failure",
                            stack_frames=trimmed_stack,
                        )
                    )
                elif error_elem is not None:
                    errors += 1
                    msg = error_elem.attrib.get("message") or (error_elem.text or "").strip()
                    stack_raw = (error_elem.text or "").splitlines()
                    trimmed_stack = StackFrameTrimmer.trim_stack(stack_raw, config)
                    failures_list.append(
                        TestFailureItem(
                            name=full_name,
                            message=msg,
                            failure_type="error",
                            stack_frames=trimmed_stack,
                        )
                    )
                elif skipped_elem is not None:
                    skipped += 1
                else:
                    passed += 1

        return NormalizedTestReport(
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_seconds=duration,
            failures=tuple(failures_list),
        )


class PytestJsonParser:
    """Parses pytest-json-report format payloads."""

    @staticmethod
    def parse(
        payload: str,
        config: TestReportCompressorConfig,
    ) -> Optional[NormalizedTestReport]:
        """Parses pytest JSON string into NormalizedTestReport."""
        try:
            doc = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(doc, dict) or "tests" not in doc:
            return None

        tests = doc.get("tests", [])
        if not isinstance(tests, list):
            return None

        passed = 0
        failed = 0
        errors = 0
        skipped = 0
        duration = float(doc.get("duration", 0.0))
        failures_list: List[TestFailureItem] = []
        other_counts: Dict[str, int] = {}

        for t in tests:
            if not isinstance(t, dict):
                continue
            outcome = str(t.get("outcome", "")).lower()
            node_id = str(t.get("nodeid", "unnamed_test"))

            call_info = t.get("call") or {}
            setup_info = t.get("setup") or {}
            teardown_info = t.get("teardown") or {}

            longrepr = (
                call_info.get("longrepr")
                or setup_info.get("longrepr")
                or teardown_info.get("longrepr")
                or ""
            )

            if outcome == "passed":
                passed += 1
            elif outcome == "failed":
                failed += 1
                msg, stack = PytestJsonParser._extract_msg_and_stack(longrepr)
                trimmed_stack = StackFrameTrimmer.trim_stack(stack, config)
                failures_list.append(
                    TestFailureItem(
                        name=node_id,
                        message=msg,
                        failure_type="failure",
                        stack_frames=trimmed_stack,
                    )
                )
            elif outcome == "skipped":
                skipped += 1
            elif outcome == "error":
                errors += 1
                msg, stack = PytestJsonParser._extract_msg_and_stack(longrepr)
                trimmed_stack = StackFrameTrimmer.trim_stack(stack, config)
                failures_list.append(
                    TestFailureItem(
                        name=node_id,
                        message=msg,
                        failure_type="error",
                        stack_frames=trimmed_stack,
                    )
                )
            else:
                other_counts[outcome] = other_counts.get(outcome, 0) + 1

        return NormalizedTestReport(
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_seconds=duration,
            other_counts=other_counts,
            failures=tuple(failures_list),
        )

    @staticmethod
    def _extract_msg_and_stack(longrepr: str) -> Tuple[str, List[str]]:
        msg = ""
        stack: List[str] = []
        for line in longrepr.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("E "):
                if not msg:
                    msg = s[2:].strip()
            elif ".py:" in s or s.startswith("at ") or s.startswith("File "):
                stack.append(s)
            elif not msg and ("Error" in s or "Exception" in s):
                msg = s
        return msg or "Test failed without explicit error message", stack


class JestJsonParser:
    """Parses Jest test reporter JSON payloads."""

    @staticmethod
    def parse(
        payload: str,
        config: TestReportCompressorConfig,
    ) -> Optional[NormalizedTestReport]:
        """Parses Jest JSON string into NormalizedTestReport."""
        try:
            doc = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(doc, dict) or "testResults" not in doc:
            return None

        passed = int(doc.get("numPassedTests", 0))
        failed = int(doc.get("numFailedTests", 0))
        skipped = int(doc.get("numPendingTests", 0))
        failures_list: List[TestFailureItem] = []

        test_results = doc.get("testResults", [])
        if isinstance(test_results, list):
            for suite in test_results:
                if not isinstance(suite, dict):
                    continue
                assertions = suite.get("assertionResults", [])
                if isinstance(assertions, list):
                    for assertion in assertions:
                        if not isinstance(assertion, dict):
                            continue
                        status = str(assertion.get("status", "")).lower()
                        if status == "failed":
                            name = assertion.get("fullName") or assertion.get("title") or "unnamed_jest_test"
                            failure_msgs = assertion.get("failureMessages", [])
                            raw_trace = "\n".join(failure_msgs) if isinstance(failure_msgs, list) else str(failure_msgs)
                            msg, stack = JestJsonParser._extract_msg_and_stack(raw_trace)
                            trimmed_stack = StackFrameTrimmer.trim_stack(stack, config)
                            failures_list.append(
                                TestFailureItem(
                                    name=name,
                                    message=msg,
                                    failure_type="failure",
                                    stack_frames=trimmed_stack,
                                )
                            )

        return NormalizedTestReport(
            passed=passed,
            failed=failed,
            skipped=skipped,
            failures=tuple(failures_list),
        )

    @staticmethod
    def _extract_msg_and_stack(raw_trace: str) -> Tuple[str, List[str]]:
        msg = ""
        stack: List[str] = []
        for line in raw_trace.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("at ") or ".test." in s or ".spec." in s:
                stack.append(s)
            elif not msg:
                msg = s
        return msg or "Test assertion failed", stack


def parse_test_report_payload(
    payload: str,
    format_kind: TestReportFormatKind,
    config: TestReportCompressorConfig,
) -> Optional[NormalizedTestReport]:
    """Dispatches payload to the corresponding specialized parser."""
    if format_kind == TestReportFormatKind.JUNIT_XML:
        return JUnitXmlParser.parse(payload, config)
    if format_kind == TestReportFormatKind.PYTEST_JSON:
        return PytestJsonParser.parse(payload, config)
    if format_kind == TestReportFormatKind.JEST_JSON:
        return JestJsonParser.parse(payload, config)
    return None
