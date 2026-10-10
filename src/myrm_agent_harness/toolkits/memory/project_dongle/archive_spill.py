"""Archive spill manager for Project Dongle suite.

[INPUT]
- Workspace directory, block lists, pointer lists, file type, line and block threshold limits.

[OUTPUT]
- ArchiveSpillManager: determines spill conditions and flushes overflowing blocks to *_ARCHIVE.md files.

[POS]
- Spill and archive overflow management for Item 152 ProjectContextUsbDongleAndCrossAgentRelaySuite.
"""

from __future__ import annotations

from pathlib import Path

from .models import DongleArchivePointer, DongleBlock, DongleBlockType


class ArchiveSpillManager:
    """Manages archiving and pointer generation when dongle markdown files exceed line or block limits."""

    def __init__(
        self,
        max_lines: int = 300,
        max_blocks: int = 50,
        spill_ratio: float = 0.4,
    ) -> None:
        self.max_lines = max_lines
        self.max_blocks = max_blocks
        self.spill_ratio = max(0.1, min(0.9, spill_ratio))

    def get_archive_filename(self, block_type: DongleBlockType) -> str:
        """Derive the corresponding archive file name for a block type."""
        base_name = block_type.value.replace(".md", "")
        return f"{base_name}_ARCHIVE.md"

    def should_spill(self, content: str, blocks_count: int) -> bool:
        """Check if content exceeds max line threshold or block count threshold."""
        line_count = len(content.splitlines())
        return line_count > self.max_lines or blocks_count > self.max_blocks

    def spill_overflow_blocks(
        self,
        workspace_dir: Path,
        block_type: DongleBlockType,
        blocks: list[DongleBlock],
        existing_pointers: list[DongleArchivePointer],
    ) -> tuple[list[DongleBlock], list[DongleArchivePointer], list[DongleArchivePointer]]:
        """Spill earliest blocks to archive file and generate pointer records.

        Returns:
            Tuple of (retained_active_blocks, all_pointers, newly_created_pointers).
        """
        if len(blocks) <= 5:
            return blocks, existing_pointers, []

        spill_count = max(1, int(len(blocks) * self.spill_ratio))
        blocks_to_archive = blocks[:spill_count]
        retained_blocks = blocks[spill_count:]

        archive_filename = self.get_archive_filename(block_type)
        archive_path = workspace_dir / archive_filename

        new_pointers: list[DongleArchivePointer] = []
        archive_lines: list[str] = []

        for b in blocks_to_archive:
            summary_text = b.content[:60].strip()
            if len(b.content) > 60:
                summary_text += "..."
            ptr = DongleArchivePointer(
                block_id=b.block_id,
                date_str=b.created_date,
                summary=summary_text,
                target_archive_file=archive_filename,
            )
            new_pointers.append(ptr)
            archive_lines.append(b.to_markdown())

        # Append blocks to archive file with header if creating for first time
        archive_exists = archive_path.exists()
        with archive_path.open("a", encoding="utf-8") as f:
            if not archive_exists:
                f.write(f"# {block_type.value.replace('.md', '')} Archive\n\n")
            for line in archive_lines:
                f.write(f"{line}\n")

        all_pointers = list(existing_pointers) + new_pointers
        return retained_blocks, all_pointers, new_pointers
