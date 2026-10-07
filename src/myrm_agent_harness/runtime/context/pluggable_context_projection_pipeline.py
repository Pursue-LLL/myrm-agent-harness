"""Pluggable context projection and entry transform pipeline engine.

Coordinates chained post-compaction entry transformations, custom domain entry
semantic projections, and emits stage-by-stage visual debugger audit records.
"""

import time

from .append_only_compaction_types import ContextLogEntry
from .entry_projectors import (
    BaseEntryProjector,
    TestCoverageDeltaProjector,
    WorkspaceTouchedFilesProjector,
)
from .entry_transforms import (
    BaseEntryTransform,
    DuplicateWarningDeduplicatorTransform,
    LongExecutionLogPrunerTransform,
)
from .pluggable_context_pipeline_types import (
    ContextPipelineExecutionReport,
    CustomContextEntry,
    PipelineStageAuditRecord,
    TransformStageKind,
)


class PluggableContextProjectionPipeline:
    """Extensible pipeline orchestrating entry transforms and custom projections."""

    def __init__(self, load_defaults: bool = True) -> None:
        """Initialize pipeline with optional default transforms and projectors."""
        self._transforms: list[tuple[int, BaseEntryTransform]] = []
        self._projectors: list[BaseEntryProjector] = []

        if load_defaults:
            self.register_transform(LongExecutionLogPrunerTransform(), priority=10)
            self.register_transform(DuplicateWarningDeduplicatorTransform(), priority=20)
            self.register_projector(WorkspaceTouchedFilesProjector())
            self.register_projector(TestCoverageDeltaProjector())

    def register_transform(self, transform: BaseEntryTransform, priority: int = 100) -> None:
        """Register an entry transform with execution priority (lower executes first)."""
        self._transforms.append((priority, transform))
        self._transforms.sort(key=lambda t: t[0])

    def register_projector(self, projector: BaseEntryProjector) -> None:
        """Register a custom entry projector."""
        self._projectors.append(projector)

    def execute_pipeline(
        self,
        retained_entries: list[ContextLogEntry],
        custom_entries: list[CustomContextEntry] | None = None,
    ) -> ContextPipelineExecutionReport:
        """Execute the multi-stage context transformation pipeline and produce visual audit."""
        custom_list = custom_entries or []
        stage_audits: list[PipelineStageAuditRecord] = []

        raw_count = len(retained_entries)
        raw_tokens = sum(e.token_estimate for e in retained_entries)

        # Stage 1: Raw Selection Audit
        stage_audits.append(
            PipelineStageAuditRecord(
                stage=TransformStageKind.RAW_SELECTION,
                transformer_name="RawContextSelector",
                entries_count_before=raw_count,
                entries_count_after=raw_count,
                tokens_before=raw_tokens,
                tokens_after=raw_tokens,
                token_delta=0,
                duration_ms=0.1,
                description=f"Initial raw selection of {raw_count} retained entries.",
            )
        )

        # Stage 2: Entry Transforms Chain
        current_entries = list(retained_entries)
        for _, transform in self._transforms:
            start_t = time.perf_counter()
            tokens_before = sum(e.token_estimate for e in current_entries)
            count_before = len(current_entries)

            transformed = transform.transform(current_entries)

            duration_ms = (time.perf_counter() - start_t) * 1000.0
            tokens_after = sum(e.token_estimate for e in transformed)
            count_after = len(transformed)
            delta = tokens_after - tokens_before

            stage_audits.append(
                PipelineStageAuditRecord(
                    stage=TransformStageKind.ENTRY_TRANSFORMS,
                    transformer_name=transform.name,
                    entries_count_before=count_before,
                    entries_count_after=count_after,
                    tokens_before=tokens_before,
                    tokens_after=tokens_after,
                    token_delta=delta,
                    duration_ms=round(duration_ms, 3),
                    description=f"Applied {transform.name}: token delta {delta:+d}.",
                )
            )
            current_entries = transformed

        # Stage 3: Custom Entry Semantic Projections
        projected_entries: list[ContextLogEntry] = []
        if custom_list:
            start_t = time.perf_counter()
            for custom in custom_list:
                for projector in self._projectors:
                    if projector.supports_type(custom.entry_type):
                        projected = projector.project(custom)
                        projected_entries.extend(projected)

            duration_ms = (time.perf_counter() - start_t) * 1000.0
            proj_tokens = sum(e.token_estimate for e in projected_entries)

            stage_audits.append(
                PipelineStageAuditRecord(
                    stage=TransformStageKind.CUSTOM_PROJECTION,
                    transformer_name="CustomEntryProjectorCoordinator",
                    entries_count_before=0,
                    entries_count_after=len(projected_entries),
                    tokens_before=0,
                    tokens_after=proj_tokens,
                    token_delta=proj_tokens,
                    duration_ms=round(duration_ms, 3),
                    description=(
                        f"Projected {len(custom_list)} custom entries into "
                        f"{len(projected_entries)} context directives (+{proj_tokens} tokens)."
                    ),
                )
            )

        # Stage 4: Final Assembly
        final_entries = projected_entries + current_entries
        final_tokens = sum(e.token_estimate for e in final_entries)
        tokens_saved = max(0, raw_tokens - sum(e.token_estimate for e in current_entries))

        stage_audits.append(
            PipelineStageAuditRecord(
                stage=TransformStageKind.FINAL_ASSEMBLY,
                transformer_name="FinalAssemblyConsolidator",
                entries_count_before=len(current_entries),
                entries_count_after=len(final_entries),
                tokens_before=raw_tokens,
                tokens_after=final_tokens,
                token_delta=final_tokens - raw_tokens,
                duration_ms=0.1,
                description=f"Final assembly assembled {len(final_entries)} total entries.",
            )
        )

        return ContextPipelineExecutionReport(
            original_entries_count=raw_count,
            final_entries=final_entries,
            total_tokens=final_tokens,
            tokens_saved=tokens_saved,
            stage_audits=stage_audits,
        )
