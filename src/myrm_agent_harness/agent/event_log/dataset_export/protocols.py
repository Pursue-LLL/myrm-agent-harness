"""Dataset export type definitions — configuration, formats, and reporting.

[INPUT]

[OUTPUT]
- ExportFormat: enum of supported output formats
- ExportConfig: export pipeline parameters
- ExportReport: summary statistics after an export run
- QualityThresholds: quality filtering parameters

[POS]
Pure type definitions. No business logic, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ExportFormat(StrEnum):
    """Supported dataset output formats."""

    SHAREGPT = "sharegpt"
    ALPACA = "alpaca"
    OPENAI = "openai"


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    """Quality filtering parameters for trace selection.

    - require_success: only include traces with SUCCESS outcome
    - min_turns: minimum conversation turns (tool_calls + llm_calls)
    - min_content_length: minimum combined length of task_input + output
    """

    require_success: bool = True
    min_turns: int = 2
    min_content_length: int = 50


@dataclass(frozen=True, slots=True)
class ExportConfig:
    """Configuration for a dataset export run.

    Args:
        output_dir: directory to write JSONL files
        formats: output formats to generate
        quality: quality filtering thresholds
        redact_pii: whether to apply PII redaction
        max_samples: maximum number of samples to export (0=unlimited)
        start_time: filter traces started after this UTC timestamp
        end_time: filter traces started before this UTC timestamp
        incremental_state_file: path to store last-exported state for incremental exports
    """

    output_dir: Path = field(default_factory=lambda: Path("dataset_exports"))
    formats: tuple[ExportFormat, ...] = (ExportFormat.SHAREGPT,)
    quality: QualityThresholds = field(default_factory=QualityThresholds)
    redact_pii: bool = True
    max_samples: int = 0
    start_time: float | None = None
    end_time: float | None = None
    incremental_state_file: Path | None = None


@dataclass(slots=True)
class ExportReport:
    """Summary statistics after an export run."""

    total_sessions_scanned: int = 0
    traces_passed_quality: int = 0
    traces_deduplicated: int = 0
    samples_exported: int = 0
    pii_redactions: int = 0
    output_files: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_sessions_scanned": self.total_sessions_scanned,
            "traces_passed_quality": self.traces_passed_quality,
            "traces_deduplicated": self.traces_deduplicated,
            "samples_exported": self.samples_exported,
            "pii_redactions": self.pii_redactions,
            "output_files": self.output_files,
            "duration_ms": round(self.duration_ms, 1),
            "errors": self.errors,
        }
