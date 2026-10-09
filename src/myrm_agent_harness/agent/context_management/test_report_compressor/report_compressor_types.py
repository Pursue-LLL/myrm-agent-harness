"""Domain contracts and data types for structured test report payload compression.

[INPUT]
- None (pure domain types, models, and enums).

[OUTPUT]
- Exports TestReportFormatKind, TestFailureItem, NormalizedTestReport,
  TestReportCompressionOutcome, and TestReportCompressorConfig.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.test_report_compressor
- Module: report_compressor_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple


class TestReportFormatKind(str, Enum):
    """Supported test report wire formats for specialized context compression."""

    JUNIT_XML = "junit_xml"
    PYTEST_JSON = "pytest_json"
    JEST_JSON = "jest_json"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TestFailureItem:
    """Represents an isolated failing test case with bounded diagnostic output."""

    name: str
    message: str
    failure_type: str = "failure"  # "failure" or "error"
    stack_frames: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NormalizedTestReport:
    """Normalized intermediate representation of an execution report across runners."""

    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    other_counts: Dict[str, int] = field(default_factory=dict)
    failures: Tuple[TestFailureItem, ...] = field(default_factory=tuple)

    @property
    def total_tests(self) -> int:
        """Returns the total number of recorded test outcomes."""
        return (
            self.passed
            + self.failed
            + self.skipped
            + self.errors
            + sum(self.other_counts.values())
        )


@dataclass(frozen=True)
class TestReportCompressorConfig:
    """Configuration options governing stack truncation and payload eligibility."""

    keep_stack_head_frames: int = 3
    keep_stack_tail_frames: int = 2
    min_stack_frames_to_trim: int = 8
    pass_through_on_zero_tests: bool = True
    max_failure_message_lines: int = 15


@dataclass(frozen=True)
class TestReportCompressionOutcome:
    """Result of attempting structured compression on an arbitrary text payload."""

    format_detected: TestReportFormatKind
    is_compressed: bool
    original_characters: int
    compressed_characters: int
    rendered_output: str
    report: Optional[NormalizedTestReport] = None
