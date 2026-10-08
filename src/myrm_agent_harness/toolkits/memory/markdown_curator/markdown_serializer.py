"""Serializes memory entries to human-friendly Markdown and parses them back.

[INPUT]
- toolkits.memory.markdown_curator.models::CuratedMemoryCategory, CuratedMemoryEntry, CuratedMemoryStatus
  (POS: Types and models for markdown curator.)

[OUTPUT]
- MarkdownMemorySerializer: Serializes memory entries to human-friendly Markdown and parses them back.

[POS]
Serializes memory entries to human-friendly Markdown and parses them back.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.markdown_curator.models import (
    CuratedMemoryCategory,
    CuratedMemoryEntry,
    CuratedMemoryStatus,
)


class MarkdownMemorySerializer:
    """Serializes memory entries to human-friendly Markdown and parses them back."""

    _ENTRY_REGEX = re.compile(
        r"^-\s+\[(?P<status_box>x| |-|r)\]\s+\*\*(?P<title>[^*]+)\*\*\s+"
        r"\(id:\s*(?P<entry_id>[^,\)]+)(?:,\s*confidence:\s*(?P<conf>[0-9.]+))?\):\s*"
        r"(?P<content>.*?)(?:\s+tags:\s*\[(?P<tags>[^\]]*)\])?$",
        re.MULTILINE,
    )

    def serialize(
        self,
        entries: list[CuratedMemoryEntry],
        doc_title: str = "Workspace Memory Mirror",
    ) -> str:
        """Render curated entries into formatted Markdown with YAML frontmatter."""
        now_iso = datetime.now(UTC).isoformat()
        total_count = len(entries)

        lines: list[str] = [
            "---",
            f"title: {doc_title}",
            "schema_version: '1.0'",
            f"updated_at: '{now_iso}'",
            f"total_entries: {total_count}",
            "---",
            "",
            f"# {doc_title}",
            "",
            "> Note: This file is a bi-directional mirror of your AI Assistant's memory.",
            "> You can directly edit, delete, or add memory items here.",
            "",
        ]

        # Group by category
        grouped: dict[CuratedMemoryCategory, list[CuratedMemoryEntry]] = {
            cat: [] for cat in CuratedMemoryCategory
        }
        for entry in entries:
            grouped[entry.category].append(entry)

        for cat in CuratedMemoryCategory:
            cat_entries = grouped[cat]
            lines.append(f"## {cat.value.capitalize()}s")
            lines.append("")
            if not cat_entries:
                lines.append(f"_No {cat.value} memories recorded yet._")
                lines.append("")
                continue

            for item in cat_entries:
                status_box = "x"
                if item.status == CuratedMemoryStatus.PENDING_CONFIRMATION:
                    status_box = " "
                elif item.status == CuratedMemoryStatus.REJECTED:
                    status_box = "r"
                elif item.status == CuratedMemoryStatus.ARCHIVED:
                    status_box = "-"

                tags_str = f" tags: [{', '.join(item.tags)}]" if item.tags else ""
                conf_str = f", confidence: {item.confidence:.2f}"
                line = (
                    f"- [{status_box}] **{item.title}** "
                    f"(id: {item.entry_id}{conf_str}): {item.content}{tags_str}"
                )
                lines.append(line)
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def deserialize(self, markdown_text: str) -> list[CuratedMemoryEntry]:
        """Parse formatted Markdown back into structured CuratedMemoryEntry objects."""
        entries: list[CuratedMemoryEntry] = []
        current_category = CuratedMemoryCategory.FACT

        lines = markdown_text.splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Detect section header
            if line.startswith("## "):
                header = line[3:].strip().lower()
                if "preference" in header:
                    current_category = CuratedMemoryCategory.PREFERENCE
                elif "fact" in header:
                    current_category = CuratedMemoryCategory.FACT
                elif "procedure" in header:
                    current_category = CuratedMemoryCategory.PROCEDURE
                elif "experience" in header:
                    current_category = CuratedMemoryCategory.EXPERIENCE
                continue

            # Parse entry item
            match = self._ENTRY_REGEX.match(line)
            if not match:
                continue

            status_box = match.group("status_box")
            status = CuratedMemoryStatus.CONFIRMED
            if status_box == " ":
                status = CuratedMemoryStatus.PENDING_CONFIRMATION
            elif status_box == "r":
                status = CuratedMemoryStatus.REJECTED
            elif status_box == "-":
                status = CuratedMemoryStatus.ARCHIVED

            title = match.group("title").strip()
            entry_id = match.group("entry_id").strip()
            conf_val = float(match.group("conf")) if match.group("conf") else 1.0
            content = match.group("content").strip()

            tags_raw = match.group("tags")
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

            entries.append(
                CuratedMemoryEntry(
                    entry_id=entry_id,
                    category=current_category,
                    title=title,
                    content=content,
                    confidence=conf_val,
                    status=status,
                    tags=tags,
                )
            )

        return entries
