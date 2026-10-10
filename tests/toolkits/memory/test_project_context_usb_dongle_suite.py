"""Unit tests for Project Context USB Dongle and cross-agent relay suite (Item 152).

[INPUT]
- Temporary workspace directories, mock block inputs, spill parameters.

[OUTPUT]
- Asserts on block parsing, prompt rendering, state loading, and archive spilling.

[POS]
- Harness test suite for Item 152 ProjectContextUsbDongleAndCrossAgentRelaySuite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.project_dongle import (
    ArchiveSpillManager,
    DongleBlock,
    DongleBlockType,
    ProjectContextDongleManager,
    parse_blocks,
    render_file,
)


def test_ensure_initialized() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace_path = Path(tmp_dir)
        manager = ProjectContextDongleManager()

        created_files = manager.ensure_initialized(workspace_path)
        assert len(created_files) == 4
        assert DongleBlockType.PROJECT_STATE.value in created_files
        assert DongleBlockType.DECISIONS.value in created_files
        assert DongleBlockType.LESSONS.value in created_files
        assert DongleBlockType.INDEX.value in created_files

        # Second run should be idempotent
        second_run = manager.ensure_initialized(workspace_path)
        assert len(second_run) == 0


def test_parse_and_render_blocks() -> None:
    raw_md = """# DECISIONS
Historic decisions for the project.

- [BLK-dec01] [2026-09-20] [arch,p0] Choose SQLite as local truth store
- Simple bullet without ID to test auto-upgrade
[archived 2026-09-15 id:dec00] Initial database selection → DECISIONS_ARCHIVE.md
"""
    blocks, pointers, headers = parse_blocks(raw_md, DongleBlockType.DECISIONS)
    assert len(blocks) == 2
    assert blocks[0].block_id == "dec01"
    assert "Choose SQLite" in blocks[0].content
    assert blocks[0].tags == ("arch", "p0")

    # Check upgraded bullet
    assert blocks[1].content == "Simple bullet without ID to test auto-upgrade"
    assert len(blocks[1].block_id) > 0

    # Check pointer
    assert len(pointers) == 1
    assert pointers[0].block_id == "dec00"
    assert pointers[0].target_archive_file == "DECISIONS_ARCHIVE.md"

    # Render back to markdown
    rendered = render_file(headers, blocks, pointers)
    assert "Choose SQLite" in rendered
    assert "[archived 2026-09-15 id:dec00]" in rendered


def test_load_dongle_context_and_render_prompt() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace_path = Path(tmp_dir)
        manager = ProjectContextDongleManager()
        manager.ensure_initialized(workspace_path)

        # Append blocks to project state and decisions
        manager.append_block(
            workspace_path,
            DongleBlock(
                block_id="st01",
                block_type=DongleBlockType.PROJECT_STATE,
                content="Architecture baseline completed",
                created_date="2026-09-27",
            ),
        )
        manager.append_block(
            workspace_path,
            DongleBlock(
                block_id="dc01",
                block_type=DongleBlockType.DECISIONS,
                content="Four-tier Markdown bullets chosen for universal portability",
                created_date="2026-09-27",
                tags=("standard", "portable"),
            ),
        )

        state = manager.load_state(workspace_path)
        assert len(state.project_state_blocks) == 1
        assert len(state.decision_blocks) == 1
        assert len(state.lesson_blocks) == 0
        assert state.total_active_blocks == 2

        prompt = manager.render_context_prompt(state)
        assert "PROJECT CONTEXT DONGLE" in prompt
        assert "Architecture baseline completed" in prompt
        assert "Four-tier Markdown bullets chosen" in prompt


def test_sync_batch_and_index_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace_path = Path(tmp_dir)
        manager = ProjectContextDongleManager()

        blocks = [
            DongleBlock(
                block_id="ls01",
                block_type=DongleBlockType.LESSONS,
                content="Avoid autocommit=True with manual transaction blocks in Python 3.13",
                created_date="2026-09-27",
            ),
            DongleBlock(
                block_id="ls02",
                block_type=DongleBlockType.LESSONS,
                content="Keep files under 400 lines and use explicit type hints",
                created_date="2026-09-27",
            ),
        ]

        result = manager.sync_batch(workspace_path, blocks)
        assert result.added_blocks_count == 2
        assert DongleBlockType.LESSONS.value in result.updated_files
        assert DongleBlockType.INDEX.value in result.updated_files

        state = manager.load_state(workspace_path)
        assert len(state.lesson_blocks) == 2
        assert "Manifest Summary" in state.index_content


def test_archive_spill_on_overflow() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace_path = Path(tmp_dir)
        # Configure small thresholds to trigger spill easily
        spill_mgr = ArchiveSpillManager(max_lines=15, max_blocks=6, spill_ratio=0.5)
        manager = ProjectContextDongleManager(spill_manager=spill_mgr)

        blocks = [
            DongleBlock(
                block_id=f"blk-{i:02d}",
                block_type=DongleBlockType.PROJECT_STATE,
                content=f"Historical milestone item number {i} with long description",
                created_date="2026-09-01",
            )
            for i in range(8)
        ]

        result = manager.sync_batch(workspace_path, blocks)
        assert result.added_blocks_count == 8
        assert result.spilled_blocks_count > 0
        assert len(result.created_pointers) > 0

        # Verify archive file was generated
        dongle_dir = manager.get_dongle_dir(workspace_path)
        archive_file = dongle_dir / "PROJECT_STATE_ARCHIVE.md"
        assert archive_file.exists()
        archive_content = archive_file.read_text(encoding="utf-8")
        assert "Historical milestone item number 0" in archive_content

        # Verify primary file retains pointers
        state = manager.load_state(workspace_path)
        assert len(state.archive_pointers) == result.spilled_blocks_count
        assert state.total_active_blocks < 8
