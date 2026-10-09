"""Master facade suite for structured test report payload compression.

[INPUT]
- report_compressor_types: NormalizedTestReport, TestReportCompressionOutcome,
  TestReportCompressorConfig, TestReportFormatKind.
- report_format_detector: TestReportFormatDetector.
- report_parsers: parse_test_report_payload.
- report_renderer: FailureFirstSummaryRenderer.

[OUTPUT]
- StructuredTestReportPayloadCompressorSuite: Master facade coordinating
  detection, normalized parsing, and failure-first summary rendering.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.test_report_compressor
- Module: test_report_compressor_suite.py
"""

from typing import Optional

from myrm_agent_harness.agent.context_management.test_report_compressor.report_compressor_types import (
    NormalizedTestReport,
    TestReportCompressionOutcome,
    TestReportCompressorConfig,
    TestReportFormatKind,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.report_format_detector import (
    TestReportFormatDetector,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.report_parsers import (
    parse_test_report_payload,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.report_renderer import (
    FailureFirstSummaryRenderer,
)


class StructuredTestReportPayloadCompressorSuite:
    """Master facade for detecting and compressing structured test report wire formats.

    Converts bulky JUnit XML, pytest-json, and Jest JSON payloads into dense,
    failure-first test summaries with bounded error messages and stack traces.
    """

    def __init__(self, config: Optional[TestReportCompressorConfig] = None) -> None:
        self._config = config or TestReportCompressorConfig()
        self._detector = TestReportFormatDetector()
        self._renderer = FailureFirstSummaryRenderer()

    @property
    def config(self) -> TestReportCompressorConfig:
        """Returns the active compressor configuration."""
        return self._config

    def looks_like_test_report(self, payload: str) -> bool:
        """Quickly checks whether the input looks like a recognized test report payload.

        Args:
            payload: Raw text from tool output or file read.

        Returns:
            True if recognized format with valid test report structure, False otherwise.
        """
        fmt = self._detector.detect_format(payload)
        if fmt == TestReportFormatKind.UNKNOWN:
            return False

        report = parse_test_report_payload(payload, fmt, self._config)
        if report is None:
            return False

        if self._config.pass_through_on_zero_tests and report.total_tests == 0:
            return False

        return True

    def compress_payload(self, payload: str) -> TestReportCompressionOutcome:
        """Compresses a test report payload if recognized and contains tests.

        If the payload is not recognized as a test report or has 0 tests (when configured
        to pass through), returns an uncompressed outcome with the original payload intact.

        Args:
            payload: Raw text string.

        Returns:
            TestReportCompressionOutcome containing compression diagnostics and output.
        """
        orig_len = len(payload)
        fmt = self._detector.detect_format(payload)

        if fmt == TestReportFormatKind.UNKNOWN:
            return TestReportCompressionOutcome(
                format_detected=TestReportFormatKind.UNKNOWN,
                is_compressed=False,
                original_characters=orig_len,
                compressed_characters=orig_len,
                rendered_output=payload,
                report=None,
            )

        report = parse_test_report_payload(payload, fmt, self._config)
        if report is None or (self._config.pass_through_on_zero_tests and report.total_tests == 0):
            return TestReportCompressionOutcome(
                format_detected=fmt,
                is_compressed=False,
                original_characters=orig_len,
                compressed_characters=orig_len,
                rendered_output=payload,
                report=report,
            )

        rendered = self._renderer.render(report, self._config)
        return TestReportCompressionOutcome(
            format_detected=fmt,
            is_compressed=True,
            original_characters=orig_len,
            compressed_characters=len(rendered),
            rendered_output=rendered,
            report=report,
        )

    def extract_report(self, payload: str) -> Optional[NormalizedTestReport]:
        """Directly parses and extracts the normalized report model without rendering."""
        fmt = self._detector.detect_format(payload)
        if fmt == TestReportFormatKind.UNKNOWN:
            return None
        return parse_test_report_payload(payload, fmt, self._config)
