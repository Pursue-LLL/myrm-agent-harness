"""Project Context USB Dongle Manager for cross-agent relay protocol.

[INPUT]
- Workspace directory, DongleBlock items, spill configuration.

[OUTPUT]
- ProjectContextDongleManager: loads, writes, renders, and synchronizes 4-tier memory blocks.

[POS]
- Core lifecycle coordinator for Item 152 ProjectContextUsbDongleAndCrossAgentRelaySuite.
"""

from __future__ import annotations

from pathlib import Path

from .archive_spill import ArchiveSpillManager
from .block_parser import parse_blocks, render_file
from .models import (
    DongleArchivePointer,
    DongleBlock,
    DongleBlockType,
    DongleState,
    SyncResult,
)

_DEFAULT_PROJECT_STATE_HEADER = """# PROJECT STATE
Current architecture status, active milestones, and ongoing subtasks.
"""

_DEFAULT_DECISIONS_HEADER = """# ARCHITECTURAL DECISIONS
Permanent technical selections, key tradeoffs, and established conventions.
"""

_DEFAULT_LESSONS_HEADER = """# LESSONS & BUG EXPERIENCES
Verified pitfalls, environment boundaries, and rules to prevent repeat failures.
"""

_DEFAULT_INDEX_HEADER = """# DONGLE INDEX
Navigation pointers and manifest for worktree project context memory.
"""


class ProjectContextDongleManager:
    """Coordinates lifecycle and synchronization of the 4-tier project memory dongle files."""

    def __init__(
        self,
        subpath: str = ".myrm/project",
        spill_manager: ArchiveSpillManager | None = None,
    ) -> None:
        self.subpath = subpath.strip("/")
        self.spill_manager = spill_manager or ArchiveSpillManager()

    def get_dongle_dir(self, workspace_path: Path) -> Path:
        """Resolve physical storage directory for dongle files."""
        if not self.subpath:
            return workspace_path
        return workspace_path / self.subpath

    def ensure_initialized(self, workspace_path: Path) -> list[str]:
        """Ensure four standard markdown files exist with valid initial headers."""
        target_dir = self.get_dongle_dir(workspace_path)
        target_dir.mkdir(parents=True, exist_ok=True)

        initialized_files: list[str] = []
        file_headers = {
            DongleBlockType.PROJECT_STATE: _DEFAULT_PROJECT_STATE_HEADER,
            DongleBlockType.DECISIONS: _DEFAULT_DECISIONS_HEADER,
            DongleBlockType.LESSONS: _DEFAULT_LESSONS_HEADER,
            DongleBlockType.INDEX: _DEFAULT_INDEX_HEADER,
        }

        for block_type, header in file_headers.items():
            file_path = target_dir / block_type.value
            if not file_path.exists():
                file_path.write_text(header.strip() + "\n\n", encoding="utf-8")
                initialized_files.append(block_type.value)

        return initialized_files

    def load_state(self, workspace_path: Path) -> DongleState:
        """Parse and aggregate the current 4-tier dongle state from disk."""
        target_dir = self.get_dongle_dir(workspace_path)
        if not target_dir.exists():
            return DongleState(workspace_dir=str(workspace_path))

        all_pointers: list[DongleArchivePointer] = []

        # 1. Project State
        ps_file = target_dir / DongleBlockType.PROJECT_STATE.value
        ps_blocks: list[DongleBlock] = []
        if ps_file.exists():
            b, p, _ = parse_blocks(ps_file.read_text(encoding="utf-8"), DongleBlockType.PROJECT_STATE)
            ps_blocks = b
            all_pointers.extend(p)

        # 2. Decisions
        dec_file = target_dir / DongleBlockType.DECISIONS.value
        dec_blocks: list[DongleBlock] = []
        if dec_file.exists():
            b, p, _ = parse_blocks(dec_file.read_text(encoding="utf-8"), DongleBlockType.DECISIONS)
            dec_blocks = b
            all_pointers.extend(p)

        # 3. Lessons
        les_file = target_dir / DongleBlockType.LESSONS.value
        les_blocks: list[DongleBlock] = []
        if les_file.exists():
            b, p, _ = parse_blocks(les_file.read_text(encoding="utf-8"), DongleBlockType.LESSONS)
            les_blocks = b
            all_pointers.extend(p)

        # 4. Index
        idx_file = target_dir / DongleBlockType.INDEX.value
        index_text = idx_file.read_text(encoding="utf-8") if idx_file.exists() else ""

        return DongleState(
            workspace_dir=str(workspace_path),
            project_state_blocks=tuple(ps_blocks),
            decision_blocks=tuple(dec_blocks),
            lesson_blocks=tuple(les_blocks),
            index_content=index_text,
            archive_pointers=tuple(all_pointers),
        )

    def render_context_prompt(self, state: DongleState) -> str:
        """Render full DongleState into Layer 1 deterministic system prompt context."""
        sections: list[str] = [
            "### [PROJECT CONTEXT DONGLE - ZERO-LOSS RELAY LAYER 1]",
            f"Workspace: {state.workspace_dir}",
        ]

        if state.project_state_blocks:
            sections.append("#### Active Project State:")
            sections.extend(b.to_markdown() for b in state.project_state_blocks)

        if state.decision_blocks:
            sections.append("#### Established Architectural Decisions:")
            sections.extend(b.to_markdown() for b in state.decision_blocks)

        if state.lesson_blocks:
            sections.append("#### Engineering Pitfalls & Lessons:")
            sections.extend(b.to_markdown() for b in state.lesson_blocks)

        if state.archive_pointers:
            sections.append("#### Archived Pointers:")
            sections.extend(p.to_markdown() for p in state.archive_pointers)

        return "\n\n".join(sections)

    def append_block(self, workspace_path: Path, block: DongleBlock) -> SyncResult:
        """Append a new block into its corresponding tier file and handle spills."""
        return self.sync_batch(workspace_path, [block])

    def sync_batch(self, workspace_path: Path, blocks: list[DongleBlock]) -> SyncResult:
        """Atomically append a batch of blocks across the 3 main tiers with spill handling."""
        self.ensure_initialized(workspace_path)
        target_dir = self.get_dongle_dir(workspace_path)

        # Group blocks by block_type
        by_type: dict[DongleBlockType, list[DongleBlock]] = {
            DongleBlockType.PROJECT_STATE: [],
            DongleBlockType.DECISIONS: [],
            DongleBlockType.LESSONS: [],
        }
        for b in blocks:
            if b.block_type in by_type:
                by_type[b.block_type].append(b)

        updated_files: list[str] = []
        newly_spilled_pointers: list[DongleArchivePointer] = []
        spilled_count = 0

        for b_type, incoming in by_type.items():
            if not incoming:
                continue

            file_path = target_dir / b_type.value
            existing_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
            curr_blocks, curr_pointers, headers = parse_blocks(existing_content, b_type)

            merged_blocks = curr_blocks + incoming

            # Check if spill is needed
            rendered_temp = render_file(headers, merged_blocks, curr_pointers)
            if self.spill_manager.should_spill(rendered_temp, len(merged_blocks)):
                retained, all_ptr, new_ptr = self.spill_manager.spill_overflow_blocks(
                    target_dir, b_type, merged_blocks, curr_pointers
                )
                merged_blocks = retained
                curr_pointers = all_ptr
                newly_spilled_pointers.extend(new_ptr)
                spilled_count += len(new_ptr)

            final_content = render_file(headers, merged_blocks, curr_pointers)
            file_path.write_text(final_content, encoding="utf-8")
            updated_files.append(b_type.value)

        # Refresh INDEX.md
        self._refresh_index_file(target_dir, updated_files, len(blocks))
        updated_files.append(DongleBlockType.INDEX.value)

        return SyncResult(
            updated_files=tuple(updated_files),
            added_blocks_count=len(blocks),
            spilled_blocks_count=spilled_count,
            created_pointers=tuple(newly_spilled_pointers),
            message=f"Synced {len(blocks)} blocks into dongle files.",
        )

    def _refresh_index_file(
        self,
        target_dir: Path,
        modified_files: list[str],
        last_added_count: int,
    ) -> None:
        """Update INDEX.md with current file metrics and pointers navigation."""
        idx_file = target_dir / DongleBlockType.INDEX.value
        existing_text = idx_file.read_text(encoding="utf-8") if idx_file.exists() else ""
        _, _, headers = parse_blocks(existing_text, DongleBlockType.INDEX)
        if not headers:
            headers = [_DEFAULT_INDEX_HEADER.strip()]

        summary_lines = [
            "### Manifest Summary",
            f"- Project State file: {DongleBlockType.PROJECT_STATE.value}",
            f"- Decisions file: {DongleBlockType.DECISIONS.value}",
            f"- Lessons file: {DongleBlockType.LESSONS.value}",
            f"- Last synced batch size: {last_added_count}",
        ]

        full_index = render_file(headers, [], []) + "\n" + "\n".join(summary_lines) + "\n"
        idx_file.write_text(full_index, encoding="utf-8")
