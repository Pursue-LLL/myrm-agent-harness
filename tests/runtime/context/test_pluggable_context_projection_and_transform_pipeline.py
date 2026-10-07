"""Unit tests for PluggableContextProjectionAndEntryTransformPipeline (Item 104).

Validates entry post-transforms (log pruner, warning deduplicator),
custom domain entry semantic projectors (touched files, test coverage),
full multi-stage pipeline orchestration, and visual debugger audit records.
"""

from myrm_agent_harness.runtime.context.append_only_compaction_types import (
    ContextEntryRole,
    ContextLogEntry,
)
from myrm_agent_harness.runtime.context.entry_projectors import (
    BaseEntryProjector,
    TestCoverageDeltaProjector,
    WorkspaceTouchedFilesProjector,
)
from myrm_agent_harness.runtime.context.entry_transforms import (
    BaseEntryTransform,
    DuplicateWarningDeduplicatorTransform,
    LongExecutionLogPrunerTransform,
)
from myrm_agent_harness.runtime.context.pluggable_context_pipeline_types import (
    CustomContextEntry,
    TransformStageKind,
)
from myrm_agent_harness.runtime.context.pluggable_context_projection_pipeline import (
    PluggableContextProjectionPipeline,
)


def test_long_execution_log_pruner_transform() -> None:
    """Verify long tool result logs are folded while preserving head and tail lines."""
    pruner = LongExecutionLogPrunerTransform(max_lines=10, head_lines=3, tail_lines=3)

    verbose_lines = [f"Line {i}: compilation in progress..." for i in range(1, 31)]
    verbose_content = "\n".join(verbose_lines)

    entry = ContextLogEntry(
        entry_id="res_01",
        role=ContextEntryRole.TOOL_RESULT,
        content=verbose_content,
        tool_call_id="call_build",
        token_estimate=600,
    )

    transformed = pruner.transform([entry])
    assert len(transformed) == 1
    result = transformed[0]

    assert "Line 1: compilation in progress..." in result.content
    assert "Line 3: compilation in progress..." in result.content
    assert "Line 28: compilation in progress..." in result.content
    assert "Line 30: compilation in progress..." in result.content
    assert "[... Truncated 24 lines of verbose execution output ...]" in result.content
    assert result.metadata.get("was_log_pruned") == "true"
    assert result.token_estimate < 600


def test_duplicate_warning_deduplicator_transform() -> None:
    """Verify repetitive warnings in tool output are collapsed."""
    deduper = DuplicateWarningDeduplicatorTransform()

    content = (
        "npm run build\n"
        "Warning: React hook missing dependency\n"
        "Warning: React hook missing dependency\n"
        "Warning: React hook missing dependency\n"
        "Build succeeded with exit code 0."
    )

    entry = ContextLogEntry(
        entry_id="res_02",
        role=ContextEntryRole.TOOL_RESULT,
        content=content,
        token_estimate=120,
    )

    transformed = deduper.transform([entry])
    assert len(transformed) == 1
    res_text = transformed[0].content

    assert "npm run build" in res_text
    assert "[Repeated warning suppressed x2]" in res_text
    assert "Build succeeded with exit code 0." in res_text


def test_custom_entry_semantic_projectors() -> None:
    """Verify custom entries (touched-files, test-coverage) project into system messages."""
    files_proj = WorkspaceTouchedFilesProjector()
    cov_proj = TestCoverageDeltaProjector()

    # 1. Touched files projection
    touched_entry = CustomContextEntry(
        entry_id="c_01",
        entry_type="touched-files",
        payload={
            "modified": "src/app.py, src/db.py",
            "added": "tests/test_db.py",
            "deleted": "legacy.py",
        },
    )
    assert files_proj.supports_type(touched_entry.entry_type) is True
    projected_files = files_proj.project(touched_entry)
    assert len(projected_files) == 1
    assert projected_files[0].role == ContextEntryRole.SYSTEM
    assert "[WORKSPACE_TOUCHED_FILES:" in projected_files[0].content
    assert "modified=[src/app.py, src/db.py]" in projected_files[0].content
    assert "added=[tests/test_db.py]" in projected_files[0].content

    # 2. Coverage delta projection
    cov_entry = CustomContextEntry(
        entry_id="c_02",
        entry_type="test-coverage-delta",
        payload={
            "coverage": "92.4%",
            "delta": "+1.8%",
            "uncovered_modules": "src/legacy_parser.py",
        },
    )
    assert cov_proj.supports_type(cov_entry.entry_type) is True
    projected_cov = cov_proj.project(cov_entry)
    assert len(projected_cov) == 1
    assert projected_cov[0].role == ContextEntryRole.SYSTEM
    assert "[TEST_COVERAGE_REPORT:" in projected_cov[0].content
    assert "overall=92.4%" in projected_cov[0].content
    assert "delta=+1.8%" in projected_cov[0].content


def test_pluggable_pipeline_full_execution_and_visual_audit_report() -> None:
    """Verify end-to-end pipeline execution and visual debugger audit records."""
    pipeline = PluggableContextProjectionPipeline(load_defaults=True)

    long_output = "\n".join([f"Processing item {i}" for i in range(1, 40)])
    entries = [
        ContextLogEntry("e1", ContextEntryRole.USER, "Run tests", token_estimate=20),
        ContextLogEntry("e2", ContextEntryRole.TOOL_RESULT, long_output, token_estimate=500),
        ContextLogEntry("e3", ContextEntryRole.ASSISTANT, "Tests finished", token_estimate=30),
    ]

    custom_entries = [
        CustomContextEntry(
            entry_id="cust_01",
            entry_type="touched-files",
            payload={"modified": "tests/unit.py"},
        )
    ]

    report = pipeline.execute_pipeline(entries, custom_entries)

    assert report.original_entries_count == 3
    # 3 transformed entries + 1 projected entry = 4 entries
    assert len(report.final_entries) == 4
    assert report.tokens_saved > 0

    # Validate visual debugger audit records across all 4 stages
    stages = [a.stage for a in report.stage_audits]
    assert TransformStageKind.RAW_SELECTION in stages
    assert TransformStageKind.ENTRY_TRANSFORMS in stages
    assert TransformStageKind.CUSTOM_PROJECTION in stages
    assert TransformStageKind.FINAL_ASSEMBLY in stages

    for audit in report.stage_audits:
        assert audit.transformer_name != ""
        assert audit.duration_ms >= 0.0


def test_custom_transform_and_projector_dynamic_registration() -> None:
    """Verify dynamic plugin extension with third-party transforms and projectors."""
    pipeline = PluggableContextProjectionPipeline(load_defaults=False)

    class CustomPrefixTransform(BaseEntryTransform):
        @property
        def name(self) -> str:
            return "CustomPrefixTransform"

        def transform(self, entries: list[ContextLogEntry]) -> list[ContextLogEntry]:
            return [
                ContextLogEntry(
                    entry_id=e.entry_id,
                    role=e.role,
                    content=f"[PREFIX] {e.content}",
                    token_estimate=e.token_estimate + 5,
                )
                for e in entries
            ]

    class CustomChecklistProjector(BaseEntryProjector):
        @property
        def name(self) -> str:
            return "CustomChecklistProjector"

        def supports_type(self, entry_type: str) -> bool:
            return entry_type == "pr-checklist"

        def project(self, entry: CustomContextEntry) -> list[ContextLogEntry]:
            return [
                ContextLogEntry(
                    entry_id=f"proj_{entry.entry_id}",
                    role=ContextEntryRole.SYSTEM,
                    content="[CHECKLIST: 3 items remaining]",
                    token_estimate=15,
                )
            ]

    pipeline.register_transform(CustomPrefixTransform(), priority=50)
    pipeline.register_projector(CustomChecklistProjector())

    entries = [ContextLogEntry("e1", ContextEntryRole.USER, "hello", token_estimate=10)]
    custom = [CustomContextEntry("c1", "pr-checklist", {})]

    report = pipeline.execute_pipeline(entries, custom)

    # 1 projected + 1 transformed entry
    assert len(report.final_entries) == 2
    assert "[CHECKLIST: 3 items remaining]" in report.final_entries[0].content
    assert "[PREFIX] hello" in report.final_entries[1].content
