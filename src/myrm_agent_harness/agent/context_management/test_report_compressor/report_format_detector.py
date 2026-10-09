"""Fast header and key-based format detection for test report payloads.

[INPUT]
- report_compressor_types: TestReportFormatKind.

[OUTPUT]
- TestReportFormatDetector: Detects whether a string payload corresponds to
  JUnit XML, pytest-json, or Jest JSON without full parsing overhead.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.test_report_compressor
- Module: report_format_detector.py
"""

import json
from typing import Dict, Optional

from myrm_agent_harness.agent.context_management.test_report_compressor.report_compressor_types import (
    TestReportFormatKind,
)


class TestReportFormatDetector:
    """Detects wire format of potential test execution reports."""

    @staticmethod
    def detect_format(payload: str) -> TestReportFormatKind:
        """Determines the test report format using top-level tag and key heuristics.

        Args:
            payload: Raw text string (from tool output or file read).

        Returns:
            TestReportFormatKind indicating the identified format or UNKNOWN.
        """
        trimmed = payload.strip()
        if not trimmed:
            return TestReportFormatKind.UNKNOWN

        # 1. XML check: starts with '<'
        if trimmed.startswith("<"):
            lower_head = trimmed[:500].lower()
            if "<testsuite" in lower_head or "<testsuites" in lower_head:
                return TestReportFormatKind.JUNIT_XML
            return TestReportFormatKind.UNKNOWN

        # 2. JSON check: starts with '{'
        if trimmed.startswith("{"):
            # Avoid full payload decoding for massive JSON if top-level structure is not a report
            try:
                # Fast parse top-level keys
                parsed = json.loads(trimmed)
                if isinstance(parsed, dict):
                    # Pytest JSON report: contains 'exitcode' and 'tests' list
                    if "exitcode" in parsed and "tests" in parsed and isinstance(parsed["tests"], list):
                        return TestReportFormatKind.PYTEST_JSON

                    # Jest JSON report: contains 'testResults' and test counters
                    if (
                        "testResults" in parsed
                        and isinstance(parsed["testResults"], list)
                        and ("numFailedTests" in parsed or "numPassedTests" in parsed or "numTotalTests" in parsed)
                    ):
                        return TestReportFormatKind.JEST_JSON
            except (json.JSONDecodeError, ValueError, TypeError):
                return TestReportFormatKind.UNKNOWN

        return TestReportFormatKind.UNKNOWN
