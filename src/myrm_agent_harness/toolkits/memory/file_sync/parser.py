"""Lenient Markdown parser for extracting structured memories with line anchors.

[INPUT]
- myrm_agent_harness.toolkits.memory.file_sync.models::FileMemoryCategory (POS: semantic categories)
- myrm_agent_harness.toolkits.memory.file_sync.models::FileMemoryEntry (POS: structured memory chunk)

[OUTPUT]
- LenientMarkdownParser: state machine parser with line-tracking and frontmatter stripping

[POS]
Fault-tolerant Markdown parser producing line-accurate memory chunks from physical documents.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.file_sync.models import (
    FileMemoryCategory,
    FileMemoryEntry,
)

_HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.+)$")
_FRONTMATTER_DELIM = "---"

_CATEGORY_KEYWORDS: dict[FileMemoryCategory, tuple[str, ...]] = {
    FileMemoryCategory.PREFERENCE: ("preference", "偏好", "习惯", "style", "风格"),
    FileMemoryCategory.RULE: ("rule", "规约", "准则", "constraint", "约束", "规范"),
    FileMemoryCategory.PROFILE: ("profile", "画像", "identity", "身份", "user", "用户"),
    FileMemoryCategory.PROCEDURAL: ("procedural", "sop", "流程", "guidance", "避坑", "经验"),
    FileMemoryCategory.EPISODIC: ("daily", "log", "episode", "事件", "记录", "日记"),
}


class LenientMarkdownParser:
    """Parser that extracts memory chunks from markdown with robust line tracking."""

    @classmethod
    def parse_document(
        cls,
        content: str,
        source_filename: str,
    ) -> list[FileMemoryEntry]:
        """Parse arbitrary markdown into a sequence of anchored memory entries."""
        lines = content.splitlines()
        if not lines:
            return []

        entries: list[FileMemoryEntry] = []
        body_lines, line_offset = cls._strip_frontmatter(lines)

        current_heading = ""
        section_lines: list[tuple[int, str]] = []

        def flush_section() -> None:
            if not section_lines:
                return
            entry = cls._create_entry_from_lines(
                lines=section_lines,
                source_filename=source_filename,
                heading=current_heading,
            )
            if entry:
                entries.append(entry)
            section_lines.clear()

        in_code_block = False
        code_fence_char = ""

        for idx, line in enumerate(body_lines, start=line_offset):
            stripped = line.strip()
            # Track fenced code blocks (``` and ~~~) to protect internal comments from heading match
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                if not in_code_block:
                    in_code_block = True
                    code_fence_char = fence
                elif fence == code_fence_char:
                    in_code_block = False
                    code_fence_char = ""
                section_lines.append((idx, line))
                continue

            if in_code_block:
                section_lines.append((idx, line))
                continue

            heading_match = _HEADING_REGEX.match(stripped)
            if heading_match:
                title = heading_match.group(2).strip()

                if section_lines:
                    flush_section()

                current_heading = title
                section_lines.append((idx, line))
            else:
                section_lines.append((idx, line))

        flush_section()
        return entries

    @classmethod
    def _strip_frontmatter(
        cls,
        lines: Sequence[str],
    ) -> tuple[Sequence[str], int]:
        """Extract or skip YAML frontmatter if present, preserving true 1-based line numbering."""
        if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
            return lines, 1

        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == _FRONTMATTER_DELIM:
                end_idx = i
                break

        if end_idx != -1 and end_idx + 1 < len(lines):
            return lines[end_idx + 1 :], end_idx + 2
        return lines, 1

    @classmethod
    def _create_entry_from_lines(
        cls,
        lines: list[tuple[int, str]],
        source_filename: str,
        heading: str,
    ) -> FileMemoryEntry | None:
        """Create a single validated entry from aggregated lines."""
        raw_text_parts: list[str] = []
        start_line = lines[0][0]
        end_line = lines[-1][0]

        for _, line_content in lines:
            raw_text_parts.append(line_content)

        full_text = "\n".join(raw_text_parts).strip()
        if not full_text:
            return None

        # Determine category based on filename, heading or content semantics
        category = cls._detect_category(source_filename, heading, full_text)

        # Stable deterministic content hash
        hasher = hashlib.sha256()
        hasher.update(source_filename.encode("utf-8"))
        hasher.update(full_text.encode("utf-8"))
        content_hash = hasher.hexdigest()

        entry_id = f"fmem_{content_hash[:16]}"

        return FileMemoryEntry(
            id=entry_id,
            content=full_text,
            source_file=source_filename,
            line_start=start_line,
            line_end=end_line,
            category=category,
            title=heading,
            content_hash=content_hash,
            metadata={"heading": heading},
        )

    @classmethod
    def _detect_category(
        cls,
        source_filename: str,
        heading: str,
        content: str,
    ) -> FileMemoryCategory:
        """Infer entry category from source path and semantic keywords."""
        lower_filename = source_filename.lower()
        if "daily" in lower_filename:
            return FileMemoryCategory.EPISODIC

        target_str = f"{heading} {content[:200]}".lower()
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in target_str for kw in keywords):
                return cat
        return FileMemoryCategory.GENERAL
