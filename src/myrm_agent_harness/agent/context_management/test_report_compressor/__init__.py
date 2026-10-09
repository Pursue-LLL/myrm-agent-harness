"""Structured test report payload compressor sub-package.

[INPUT]
- report_compressor_types: TestReportFormatKind, TestFailureItem,
  NormalizedTestReport, TestReportCompressionOutcome, TestReportCompressorConfig.
- report_format_detector: TestReportFormatDetector.
- report_parsers: JUnitXmlParser, PytestJsonParser, JestJsonParser,
  StackFrameTrimmer, parse_test_report_payload.
- report_renderer: FailureFirstSummaryRenderer.
- test_report_compressor_suite: StructuredTestReportPayloadCompressorSuite.

[OUTPUT]
- Seamless package exports of all domain types, parsers, and master facade suite.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.test_report_compressor
- Module: __init__.py
"""

from myrm_agent_harness.agent.context_management.test_report_compressor.report_compressor_types import (
    NormalizedTestReport,
    TestFailureItem,
    TestReportCompressionOutcome,
    TestReportCompressorConfig,
    TestReportFormatKind,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.report_format_detector import (
    TestReportFormatDetector,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.report_parsers import (
    JestJsonParser,
    JUnitXmlParser,
    PytestJsonParser,
    StackFrameTrimmer,
    parse_test_report_payload,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.report_renderer import (
    FailureFirstSummaryRenderer,
)
from myrm_agent_harness.agent.context_management.test_report_compressor.test_report_compressor_suite import (
    StructuredTestReportPayloadCompressorSuite,
)

__all__ = [
    "FailureFirstSummaryRenderer",
    "JestJsonParser",
    "JUnitXmlParser",
    "NormalizedTestReport",
    "PytestJsonParser",
    "StackFrameTrimmer",
    "StructuredTestReportPayloadCompressorSuite",
    "TestFailureItem",
    "TestReportCompressionOutcome",
    "TestReportCompressorConfig",
    "TestReportFormatKind",
    "TestReportFormatDetector",
    "parse_test_report_payload",
]
