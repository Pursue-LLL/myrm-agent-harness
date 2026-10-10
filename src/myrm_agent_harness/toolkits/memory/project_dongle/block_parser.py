"""Markdown bullet block and archive pointer parser for Project Dongle suite.

[INPUT]
- Raw markdown text, DongleBlockType enum, and block formatting rules.

[OUTPUT]
- parse_blocks: Extracts DongleBlock items, DongleArchivePointer items, and structural headers.
- render_file: Formats header lines, blocks, and pointers into clean standard Markdown.

[POS]
- Block parsing and formatting engine for Item 152 ProjectContextUsbDongleAndCrossAgentRelaySuite.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from .models import DongleArchivePointer, DongleBlock, DongleBlockType

# Matches: - [BLK-c9bf60] [2026-09-27] [tag1,tag2] Actual content
_BLOCK_RE = re.compile(
    r"^\s*-\s+\[BLK-(?P<id>[a-zA-Z0-9_-]+)\]\s+\[(?P<date>[0-9-]+)\](?:\s+\[(?P<tags>[^\]]*)\])?\s+(?P<content>.+)$"
)

# Matches legacy/simple bullet: - Actual content
_SIMPLE_BULLET_RE = re.compile(r"^\s*-\s+(?P<content>.+)$")

# Matches: [archived 2026-09-19 id:c9bf60] Summary text → DECISIONS_ARCHIVE.md
_POINTER_RE = re.compile(
    r"^\s*\[archived\s+(?P<date>[0-9-]+)\s+id:(?P<id>[a-zA-Z0-9_-]+)\]\s+(?P<summary>.+?)\s+→\s+(?P<target>\S+)\s*$"
)


def parse_blocks(
    content: str,
    block_type: DongleBlockType,
) -> tuple[list[DongleBlock], list[DongleArchivePointer], list[str]]:
    """Parse markdown content into structured DongleBlocks, archive pointers, and header lines."""
    blocks: list[DongleBlock] = []
    pointers: list[DongleArchivePointer] = []
    header_lines: list[str] = []

    lines = content.splitlines()
    in_header = True

    today_str = datetime.now(UTC).strftime("%Y-%m-%d")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_header:
                header_lines.append(line)
            continue

        # Check for archive pointer line
        ptr_match = _POINTER_RE.match(stripped)
        if ptr_match:
            in_header = False
            pointers.append(
                DongleArchivePointer(
                    block_id=ptr_match.group("id"),
                    date_str=ptr_match.group("date"),
                    summary=ptr_match.group("summary").strip(),
                    target_archive_file=ptr_match.group("target"),
                )
            )
            continue

        # Check for standard [BLK-xxx] bullet
        block_match = _BLOCK_RE.match(stripped)
        if block_match:
            in_header = False
            raw_tags = block_match.group("tags")
            tags = tuple(t.strip() for t in raw_tags.split(",")) if raw_tags else ()
            blocks.append(
                DongleBlock(
                    block_id=block_match.group("id"),
                    block_type=block_type,
                    content=block_match.group("content").strip(),
                    created_date=block_match.group("date"),
                    tags=tags,
                )
            )
            continue

        # Check for simple bullet without block id: upgrade it with generated ID
        simple_match = _SIMPLE_BULLET_RE.match(stripped)
        if simple_match:
            in_header = False
            gen_id = uuid.uuid4().hex[:6]
            blocks.append(
                DongleBlock(
                    block_id=gen_id,
                    block_type=block_type,
                    content=simple_match.group("content").strip(),
                    created_date=today_str,
                    tags=(),
                )
            )
            continue

        # Non-bullet structural line (heading, prose intro, etc.)
        if in_header:
            header_lines.append(line)

    return blocks, pointers, header_lines


def render_file(
    header_lines: list[str],
    blocks: list[DongleBlock],
    pointers: list[DongleArchivePointer],
) -> str:
    """Render structured components into clean, deterministic Markdown text."""
    parts: list[str] = []

    # 1. Header lines
    if header_lines:
        clean_header = "\n".join(header_lines).strip()
        if clean_header:
            parts.append(clean_header)

    # 2. Active blocks
    if blocks:
        block_lines = [b.to_markdown() for b in blocks]
        parts.append("\n".join(block_lines))

    # 3. Archive pointers section
    if pointers:
        pointer_section: list[str] = ["\n### Archive Pointers"]
        for p in pointers:
            pointer_section.append(p.to_markdown())
        parts.append("\n".join(pointer_section))

    return "\n\n".join(parts) + "\n"
