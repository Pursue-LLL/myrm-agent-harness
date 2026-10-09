"""Comprehensive unit test suite for StructuredTestReportPayloadCompressorSuite.

[INPUT]
- test_report_compressor types, detector, parsers, renderer, and master facade suite.

[OUTPUT]
- Deterministic verification of JUnit XML, pytest JSON, Jest JSON format detection,
  failure-first compact summary rendering, stack frame bounded folding, zero-test pass-through,
  and package root exports.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_structured_test_report_compressor_suite.py
"""

from typing import Dict, List

import pytest

from myrm_agent_harness.agent import (
    StructuredTestReportPayloadCompressorSuite as RootExportedSuite,
)
from myrm_agent_harness.agent.context_management import (
    FailureFirstSummaryRenderer,
    JestJsonParser,
    JUnitXmlParser,
    NormalizedTestReport,
    PytestJsonParser,
    StackFrameTrimmer,
    StructuredTestReportPayloadCompressorSuite,
    TestFailureItem as FailureItem,
    TestReportCompressionOutcome as CompressionOutcome,
    TestReportCompressorConfig as ReportCompressorConfig,
    TestReportFormatDetector as ReportFormatDetector,
    TestReportFormatKind as ReportFormatKind,
)


def test_junit_xml_compression_with_failures_and_errors() -> None:
    """Verifies that multi-suite JUnit XML is accurately parsed into failure-first summary."""
    junit_xml = """<?xml version="1.0" encoding="utf-8"?>
    <testsuites time="12.4">
        <testsuite name="BillingTests" time="5.2" tests="3" failures="1" errors="0" skipped="0">
            <testcase name="test_charge_success" classname="billing.test_core" time="1.0"/>
            <testcase name="test_refund_success" classname="billing.test_core" time="1.1"/>
            <testcase name="test_card_declined" classname="billing.test_core" time="3.1">
                <failure message="PaymentGatewayError: Insufficient funds">
Traceback (most recent call last):
  File "billing/test_core.py", line 45, in test_card_declined
    gateway.charge(card, 1000)
  File "billing/gateway.py", line 12, in charge
    raise PaymentGatewayError("Insufficient funds")
PaymentGatewayError: Insufficient funds
                </failure>
            </testcase>
        </testsuite>
        <testsuite name="AuthTests" time="7.2" tests="2" failures="0" errors="1" skipped="1">
            <testcase name="test_token_expired" classname="auth.test_jwt" time="0.5">
                <skipped/>
            </testcase>
            <testcase name="test_db_deadlock" classname="auth.test_jwt" time="6.7">
                <error message="DeadlockDetected">
  File "auth/test_jwt.py", line 88, in test_db_deadlock
    db.acquire_lock()
OperationalError: DeadlockDetected
                </error>
            </testcase>
        </testsuite>
    </testsuites>
    """

    suite = StructuredTestReportPayloadCompressorSuite()
    assert suite.looks_like_test_report(junit_xml) is True

    outcome = suite.compress_payload(junit_xml)
    assert outcome.is_compressed is True
    assert outcome.format_detected == ReportFormatKind.JUNIT_XML
    assert outcome.compressed_characters < outcome.original_characters

    out = outcome.rendered_output
    assert "TEST SUMMARY: 2 passed, 1 failed, 1 errors, 1 skipped (12.4s)" in out
    assert "FAILED: billing.test_core::test_card_declined" in out
    assert "PaymentGatewayError: Insufficient funds" in out
    assert 'File "billing/test_core.py", line 45, in test_card_declined' in out
    assert "ERROR: auth.test_jwt::test_db_deadlock" in out
    assert "DeadlockDetected" in out


def test_pytest_json_report_compression() -> None:
    """Verifies pytest-json-report format parser and failure-first output."""
    pytest_json = """{
        "created": 1700000000.0,
        "duration": 3.82,
        "exitcode": 1,
        "root": "/workspace/repo",
        "environment": {"Python": "3.13.0"},
        "summary": {"passed": 2, "failed": 1, "total": 3},
        "tests": [
            {
                "nodeid": "tests/test_api.py::test_get_user_200",
                "outcome": "passed",
                "setup": {"duration": 0.01, "outcome": "passed"},
                "call": {"duration": 0.12, "outcome": "passed"}
            },
            {
                "nodeid": "tests/test_api.py::test_get_user_404",
                "outcome": "passed",
                "setup": {"duration": 0.01, "outcome": "passed"},
                "call": {"duration": 0.08, "outcome": "passed"}
            },
            {
                "nodeid": "tests/test_api.py::test_post_invalid_json",
                "outcome": "failed",
                "setup": {"duration": 0.01, "outcome": "passed"},
                "call": {
                    "duration": 0.25,
                    "outcome": "failed",
                    "longrepr": "def test_post_invalid_json():\\n>       assert response.status_code == 400\\nE       assert 500 == 400\\ntests/test_api.py:55: AssertionError"
                }
            }
        ]
    }"""

    suite = StructuredTestReportPayloadCompressorSuite()
    assert suite.looks_like_test_report(pytest_json) is True

    outcome = suite.compress_payload(pytest_json)
    assert outcome.is_compressed is True
    assert outcome.format_detected == ReportFormatKind.PYTEST_JSON
    out = outcome.rendered_output

    assert "TEST SUMMARY: 2 passed, 1 failed (3.8s)" in out
    assert "FAILED: tests/test_api.py::test_post_invalid_json" in out
    assert "assert 500 == 400" in out
    assert "tests/test_api.py:55: AssertionError" in out


def test_jest_json_report_compression() -> None:
    """Verifies Jest JSON reporter format parsing and failure message normalization."""
    jest_json = """{
        "numFailedTestSuites": 1,
        "numFailedTests": 1,
        "numPassedTestSuites": 1,
        "numPassedTests": 5,
        "numPendingTestSuites": 0,
        "numPendingTests": 1,
        "numTotalTestSuites": 2,
        "numTotalTests": 7,
        "testResults": [
            {
                "name": "/workspace/repo/src/Button.test.tsx",
                "status": "passed",
                "assertionResults": [
                    {"title": "renders with text", "status": "passed", "ancestorTitles": ["Button"]}
                ]
            },
            {
                "name": "/workspace/repo/src/Form.test.tsx",
                "status": "failed",
                "assertionResults": [
                    {
                        "title": "submits valid payload",
                        "fullName": "Form › submits valid payload",
                        "status": "failed",
                        "failureMessages": [
                            "Error: expect(received).toHaveBeenCalledWith(expected)\\n\\nExpected: {\\"id\\": 1}\\nReceived: {\\"id\\": 2}\\n    at Object.<anonymous> (/workspace/repo/src/Form.test.tsx:42:25)\\n    at Promise.then.completed (/workspace/node_modules/jest-circus/build/utils.js:333:28)"
                        ]
                    }
                ]
            }
        ]
    }"""

    suite = StructuredTestReportPayloadCompressorSuite()
    assert suite.looks_like_test_report(jest_json) is True

    outcome = suite.compress_payload(jest_json)
    assert outcome.is_compressed is True
    assert outcome.format_detected == ReportFormatKind.JEST_JSON
    out = outcome.rendered_output

    assert "TEST SUMMARY: 5 passed, 1 failed, 1 skipped" in out
    assert "FAILED: Form › submits valid payload" in out
    assert "Error: expect(received).toHaveBeenCalledWith(expected)" in out
    assert "at Object.<anonymous> (/workspace/repo/src/Form.test.tsx:42:25)" in out


def test_stack_frame_trimming_elides_middle() -> None:
    """Verifies that overly verbose stack traces keep head and tail frames, folding the middle."""
    config = ReportCompressorConfig(
        keep_stack_head_frames=3,
        keep_stack_tail_frames=2,
        min_stack_frames_to_trim=8,
    )

    frames = [
        f"  at com.example.service.Layer{i}.execute(Layer{i}.java:{i * 10})"
        for i in range(1, 15)
    ]

    trimmed = StackFrameTrimmer.trim_stack(frames, config)
    assert len(trimmed) == 6  # 3 head + 1 omitted note + 2 tail
    assert "Layer1.java:10" in trimmed[0]
    assert "Layer2.java:20" in trimmed[1]
    assert "Layer3.java:30" in trimmed[2]
    assert "... (9 frames omitted)" in trimmed[3]
    assert "Layer13.java:130" in trimmed[4]
    assert "Layer14.java:140" in trimmed[5]


def test_all_passed_yields_compact_single_line_summary() -> None:
    """Verifies that green test runs produce a minimal single-line summary with zero failure noise."""
    green_junit = """<testsuite tests="50" failures="0" errors="0" skipped="2" time="4.5">
        <testcase name="test_01"/><testcase name="test_02"/>
    </testsuite>"""

    suite = StructuredTestReportPayloadCompressorSuite()
    outcome = suite.compress_payload(green_junit)

    assert outcome.is_compressed is True
    lines = outcome.rendered_output.strip().splitlines()
    assert len(lines) == 1
    assert lines[0] == "TEST SUMMARY: 2 passed (4.5s)"


def test_pass_through_on_zero_tests_and_unknown_payloads() -> None:
    """Verifies that non-report text or zero-test documents pass through without modification."""
    suite = StructuredTestReportPayloadCompressorSuite()

    # 1. Plain text payload
    plain = "Building target 'all'... Done in 2.3s."
    assert suite.looks_like_test_report(plain) is False
    out_plain = suite.compress_payload(plain)
    assert out_plain.is_compressed is False
    assert out_plain.rendered_output == plain

    # 2. Arbitrary JSON
    arb_json = '{"user": "alice", "preferences": {"theme": "dark"}}'
    assert suite.looks_like_test_report(arb_json) is False
    out_json = suite.compress_payload(arb_json)
    assert out_json.is_compressed is False
    assert out_json.rendered_output == arb_json

    # 3. Empty testsuite XML
    empty_xml = '<testsuite name="empty" tests="0" time="0.0"/>'
    assert suite.looks_like_test_report(empty_xml) is False
    out_empty = suite.compress_payload(empty_xml)
    assert out_empty.is_compressed is False
    assert out_empty.rendered_output == empty_xml


def test_package_and_root_exports() -> None:
    """Verifies clean lazy loading and type conformance from package root."""
    assert RootExportedSuite is StructuredTestReportPayloadCompressorSuite
    suite = RootExportedSuite()
    assert isinstance(suite, StructuredTestReportPayloadCompressorSuite)
    assert suite.config is not None
