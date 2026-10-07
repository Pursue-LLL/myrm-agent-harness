"""Types and data contracts for browser automation batch processing and script synthesis.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ArtifactFormatKind: Output format for batch extracted datasets.
- PaginationStrategy: Pagination mechanism used in automated web navigation.
- BatchFieldSpec: Definition of a structured attribute to extract.
- BatchExtractionIntent: Specification of a long-running batch crawling goal.
- SynthesizedBrowserScript: Autonomous self-contained batch execution script for sandbox.
- DashboardMetricCard: KPI card specification for generated dashboard.
- InteractiveDashboardSpec: In-situ interactive dashboard component specification.
- BatchExecutionResult: Single-turn compacted result preventing context explosion.

[POS]
Data contracts for batch script generation, single-turn context distillation, and dashboard compilation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ArtifactFormatKind(str, Enum):
    """Output format for batch extracted datasets."""

    EXCEL = "xlsx"
    CSV = "csv"
    JSON = "json"


class PaginationStrategy(str, Enum):
    """Pagination mechanism used in automated web navigation."""

    NEXT_BUTTON_CLICK = "next_button_click"
    URL_OFFSET = "url_offset"
    INFINITE_SCROLL = "infinite_scroll"


@dataclass(frozen=True, slots=True)
class BatchFieldSpec:
    """Definition of a structured attribute to extract from each item."""

    field_name: str
    css_selector: str
    description: str
    is_required: bool = False


@dataclass(frozen=True, slots=True)
class BatchExtractionIntent:
    """Specification of a long-running batch crawling goal.

    Converts high-level goals (e.g. 'collect 30 job postings') into a concrete plan
    to be compiled into a sandbox script rather than executed step-by-step.
    """

    target_url: str
    target_count: int
    fields: tuple[BatchFieldSpec, ...]
    pagination_strategy: PaginationStrategy
    pagination_selector_or_param: str
    dedup_key: str
    output_format: ArtifactFormatKind = ArtifactFormatKind.EXCEL
    generate_dashboard: bool = True
    max_pages: int = 10


@dataclass(frozen=True, slots=True)
class SynthesizedBrowserScript:
    """Autonomous self-contained batch execution script for the sandbox environment."""

    script_id: str
    target_url: str
    python_code: str
    required_packages: tuple[str, ...]
    timeout_seconds: int = 120
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class DashboardMetricCard:
    """KPI card specification for the generated interactive dashboard."""

    label: str
    value: str
    unit: str = ""
    highlight: str = ""


@dataclass(frozen=True, slots=True)
class InteractiveDashboardSpec:
    """In-situ interactive dashboard component specification."""

    dashboard_title: str
    summary_cards: tuple[DashboardMetricCard, ...]
    chart_distribution: dict[str, int]
    table_preview_columns: tuple[str, ...]
    artifact_download_path: str
    component_tsx_code: str


@dataclass(frozen=True, slots=True)
class BatchExecutionResult:
    """Single-turn compacted result preventing context explosion.

    Compresses megabytes of raw HTML / DOM round-trips into a compact summary
    plus a persisted file pointer and optional dashboard artifact.
    """

    intent_url: str
    total_extracted: int
    deduped_count: int
    artifact_path: str
    sample_records: tuple[dict[str, str], ...]
    estimated_tokens_saved: int
    compact_context_text: str
    dashboard_spec: InteractiveDashboardSpec | None = None
