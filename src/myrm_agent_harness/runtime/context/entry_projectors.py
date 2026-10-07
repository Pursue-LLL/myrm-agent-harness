"""Entry projector plugins for translating custom entries into LLM context messages.

Allows extensions and tools to inject domain-specific state (e.g. workspace touched
files, test coverage deltas) into the model's active context window safely.

[INPUT]
- runtime.context.append_only_compaction_types::ContextEntryRole, ContextLogEntry (POS: Types for
  append-only compaction ledger and atomic tool-pair cut-point engine.)
- runtime.context.pluggable_context_pipeline_types::CustomContextEntry (POS: Types for pluggable context
  projection and entry transform pipeline.)

[OUTPUT]
- BaseEntryProjector: Abstract base class for custom entry semantic projectors.
- WorkspaceTouchedFilesProjector: Projects workspace file mutation history into a concise system directive.
- TestCoverageDeltaProjector: Projects test suite execution coverage metrics into LLM guidance.

[POS]
Entry projector plugins for translating custom entries into LLM context messages.
"""

from abc import ABC, abstractmethod

from .append_only_compaction_types import ContextEntryRole, ContextLogEntry
from .pluggable_context_pipeline_types import CustomContextEntry


class BaseEntryProjector(ABC):
    """Abstract base class for custom entry semantic projectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this projector."""

    @abstractmethod
    def supports_type(self, entry_type: str) -> bool:
        """Check whether this projector handles the given custom entry type."""

    @abstractmethod
    def project(self, entry: CustomContextEntry) -> list[ContextLogEntry]:
        """Project custom entry into one or more standard ContextLogEntry instances."""


class WorkspaceTouchedFilesProjector(BaseEntryProjector):
    """Projects workspace file mutation history into a concise system directive."""

    @property
    def name(self) -> str:
        """Projector name."""
        return "WorkspaceTouchedFilesProjector"

    def supports_type(self, entry_type: str) -> bool:
        """Supports touched-files custom entries."""
        return entry_type in ("touched-files", "workspace_touched_files")

    def project(self, entry: CustomContextEntry) -> list[ContextLogEntry]:
        """Format modified, added, and deleted files into a structured context message."""
        modified = entry.payload.get("modified", "").strip()
        added = entry.payload.get("added", "").strip()
        deleted = entry.payload.get("deleted", "").strip()

        parts: list[str] = []
        if modified:
            parts.append(f"modified=[{modified}]")
        if added:
            parts.append(f"added=[{added}]")
        if deleted:
            parts.append(f"deleted=[{deleted}]")

        summary_text = ", ".join(parts) if parts else "no files changed"
        content = f"[WORKSPACE_TOUCHED_FILES: {summary_text}]"
        tokens = max(15, len(content) // 4)

        return [
            ContextLogEntry(
                entry_id=f"proj_{entry.entry_id}",
                role=ContextEntryRole.SYSTEM,
                content=content,
                token_estimate=tokens,
                metadata={"projected_from": entry.entry_id, "projector": self.name},
            )
        ]


class TestCoverageDeltaProjector(BaseEntryProjector):
    """Projects test suite execution coverage metrics into LLM guidance."""

    @property
    def name(self) -> str:
        """Projector name."""
        return "TestCoverageDeltaProjector"

    def supports_type(self, entry_type: str) -> bool:
        """Supports test-coverage-delta custom entries."""
        return entry_type in ("test-coverage-delta", "coverage_report")

    def project(self, entry: CustomContextEntry) -> list[ContextLogEntry]:
        """Format test coverage delta metrics into a structured directive."""
        cov_pct = entry.payload.get("coverage", "unknown")
        delta = entry.payload.get("delta", "+0.0%")
        uncovered = entry.payload.get("uncovered_modules", "none")

        content = (
            f"[TEST_COVERAGE_REPORT: overall={cov_pct}, "
            f"delta={delta}, uncovered=[{uncovered}]]"
        )
        tokens = max(15, len(content) // 4)

        return [
            ContextLogEntry(
                entry_id=f"proj_{entry.entry_id}",
                role=ContextEntryRole.SYSTEM,
                content=content,
                token_estimate=tokens,
                metadata={"projected_from": entry.entry_id, "projector": self.name},
            )
        ]
