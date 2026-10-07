"""Type contracts for LCA branch exploration summary and cumulative file tracking.

Defines immutable data models for cumulative read/write footprints,
structured branch exploration handoff summaries, and LCA handoff results.
Strictly adheres to 0 Any and typed dataclasses.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- CumulativeFileFootprint: Immutable record of cumulative files read and modified across cycles and
  branches.
- BranchExplorationSummary: Structured synthesis of discarded branch exploration experiences.
- BranchHandoffResult: Result of an LCA branch handoff computation and summary mounting.

[POS]
Type contracts for LCA branch exploration summary and cumulative file tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CumulativeFileFootprint:
    """Immutable record of cumulative files read and modified across cycles and branches."""

    read_files: tuple[str, ...] = ()
    modified_files: tuple[str, ...] = ()

    def union(
        self,
        other: CumulativeFileFootprint | None = None,
        *,
        extra_reads: tuple[str, ...] = (),
        extra_modified: tuple[str, ...] = (),
    ) -> CumulativeFileFootprint:
        """Return a new CumulativeFileFootprint representing the sorted mathematical union."""
        all_reads = set(self.read_files)
        all_mods = set(self.modified_files)

        if other is not None:
            all_reads.update(other.read_files)
            all_mods.update(other.modified_files)

        all_reads.update(extra_reads)
        all_mods.update(extra_modified)

        return CumulativeFileFootprint(
            read_files=tuple(sorted(all_reads)),
            modified_files=tuple(sorted(all_mods)),
        )

    def render_xml_block(self) -> str:
        """Render structural XML block for context prompt injection."""
        sections: list[str] = []
        if self.read_files:
            lines = ["<cumulative-read-files>"]
            for path in sorted(self.read_files):
                lines.append(f"  <file>{path}</file>")
            lines.append("</cumulative-read-files>")
            sections.append("\n".join(lines))

        if self.modified_files:
            lines = ["<cumulative-modified-files>"]
            for path in sorted(self.modified_files):
                lines.append(f"  <file>{path}</file>")
            lines.append("</cumulative-modified-files>")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def render_markdown_block(self) -> str:
        """Render readable markdown list for visual reporting and prompt inclusion."""
        parts: list[str] = []
        if self.read_files:
            items = "\n".join(f"- `{f}`" for f in sorted(self.read_files))
            parts.append(f"### Cumulative Read Files ({len(self.read_files)})\n{items}")
        if self.modified_files:
            items = "\n".join(f"- `{f}`" for f in sorted(self.modified_files))
            parts.append(f"### Cumulative Modified Files ({len(self.modified_files)})\n{items}")
        return "\n\n".join(parts)


@dataclass(frozen=True, slots=True)
class BranchExplorationSummary:
    """Structured synthesis of discarded branch exploration experiences."""

    goal: str
    progress_achieved: tuple[str, ...]
    key_decisions: tuple[str, ...]
    pitfalls_and_lessons: tuple[str, ...]
    abandoned_leads: tuple[str, ...]
    cumulative_files: CumulativeFileFootprint
    source_leaf_id: str
    target_node_id: str
    lca_node_id: str | None
    abandoned_entry_count: int
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def render_markdown(self) -> str:
        """Render standardized markdown block for prompt injection into destination branch."""
        sections = [
            f"## Branch Exploration Insights (From: `{self.source_leaf_id}` to `{self.target_node_id}`)",
            f"**LCA Common Ancestor**: `{self.lca_node_id or 'ROOT'}` | **Explored Nodes**: {self.abandoned_entry_count}",
            f"### Abandoned Goal\n{self.goal or 'N/A'}",
        ]

        if self.progress_achieved:
            sections.append(
                "### Progress & Findings\n"
                + "\n".join(f"- {p}" for p in self.progress_achieved)
            )
        if self.key_decisions:
            sections.append(
                "### Key Architectural Decisions\n"
                + "\n".join(f"- {d}" for d in self.key_decisions)
            )
        if self.pitfalls_and_lessons:
            sections.append(
                "### Pitfalls & Negative Lessons (Do Not Repeat)\n"
                + "\n".join(f"- {lesson}" for lesson in self.pitfalls_and_lessons)
            )
        if self.abandoned_leads:
            sections.append(
                "### Remaining Leads / Next Steps\n"
                + "\n".join(f"- {lead}" for lead in self.abandoned_leads)
            )

        file_xml = self.cumulative_files.render_xml_block()
        if file_xml:
            sections.append(f"### File Footprint\n{file_xml}")

        return "\n\n".join(sections)


@dataclass(frozen=True, slots=True)
class BranchHandoffResult:
    """Result of an LCA branch handoff computation and summary mounting."""

    source_leaf_id: str
    target_node_id: str
    lca_node_id: str | None
    abandoned_entries_count: int
    summary: BranchExplorationSummary | None
    inherited_cumulative_files: CumulativeFileFootprint
    is_noop: bool = False
