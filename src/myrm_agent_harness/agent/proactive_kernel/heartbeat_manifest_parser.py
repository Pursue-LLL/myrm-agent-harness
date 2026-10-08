"""Parser and serializer for HEARTBEAT.md proactive micro-kernel manifests.

[INPUT]
- proactive_kernel_types::HeartbeatChecklistItem, HeartbeatManifest, OpportunityCategory, ProactivityLevel (POS: Domain models)

[OUTPUT]
- HeartbeatManifestParser: Parses Markdown + Frontmatter HEARTBEAT.md files into typed manifests.

[POS]
Specification parser for OpenClaw-inspired HEARTBEAT.md manifests, enabling developers
and users to govern background autonomous inspection cadences via standard Markdown.
"""

from __future__ import annotations

import re

from .proactive_kernel_types import (
    HeartbeatChecklistItem,
    HeartbeatManifest,
    OpportunityCategory,
    ProactivityLevel,
)


class HeartbeatManifestParser:
    """Parses and formats HEARTBEAT.md markdown specifications."""

    _DEFAULT_INTERVAL_MINUTES = 15
    _DEFAULT_LEVEL = ProactivityLevel.BALANCED
    _DEFAULT_MAX_DOCKED_HOURLY = 2

    _CHECKLIST_REGEX = re.compile(
        r"^\s*-\s*\[([ xX])\]\s*(.*?)(?:\s*\((?:category|tag):\s*([a-zA-Z0-9_-]+)\))?$",
        re.MULTILINE,
    )
    _INTERVAL_REGEX = re.compile(r"^\s*interval(?:_minutes)?:\s*(\d+)", re.IGNORECASE | re.MULTILINE)
    _LEVEL_REGEX = re.compile(r"^\s*proactivity(?:_level)?:\s*([a-zA-Z]+)", re.IGNORECASE | re.MULTILINE)
    _MAX_DOCKED_REGEX = re.compile(r"^\s*max_docked(?:_per_hour)?:\s*(\d+)", re.IGNORECASE | re.MULTILINE)

    @classmethod
    def parse_manifest(cls, markdown_content: str | None) -> HeartbeatManifest:
        """Parse raw HEARTBEAT.md markdown string into a typed HeartbeatManifest."""
        if not markdown_content or not markdown_content.strip():
            return cls.build_default_manifest()

        raw_text = markdown_content.strip()

        # 1. Parse configuration parameters
        interval = cls._DEFAULT_INTERVAL_MINUTES
        interval_match = cls._INTERVAL_REGEX.search(raw_text)
        if interval_match:
            try:
                interval = max(int(interval_match.group(1)), 1)
            except ValueError:
                pass

        level = cls._DEFAULT_LEVEL
        level_match = cls._LEVEL_REGEX.search(raw_text)
        if level_match:
            lvl_str = level_match.group(1).lower()
            for cand in ProactivityLevel:
                if cand.value == lvl_str:
                    level = cand
                    break

        max_docked = cls._DEFAULT_MAX_DOCKED_HOURLY
        max_docked_match = cls._MAX_DOCKED_REGEX.search(raw_text)
        if max_docked_match:
            try:
                max_docked = max(int(max_docked_match.group(1)), 1)
            except ValueError:
                pass

        # 2. Parse checklist items
        items: list[HeartbeatChecklistItem] = []
        matches = cls._CHECKLIST_REGEX.findall(raw_text)
        for idx, (check_box, desc, cat_tag) in enumerate(matches):
            is_active = check_box.strip().lower() == "x"
            category = cls._resolve_category(cat_tag, desc)
            item_id = f"hb_chk_{idx + 1}"
            items.append(
                HeartbeatChecklistItem(
                    item_id=item_id,
                    description=desc.strip(),
                    target_category=category,
                    is_active=is_active,
                )
            )

        if not items:
            items = list(cls.build_default_manifest().checklist_items)

        return HeartbeatManifest(
            interval_minutes=interval,
            proactivity_level=level,
            checklist_items=tuple(items),
            max_docked_per_hour=max_docked,
            raw_markdown_source=raw_text,
        )

    @classmethod
    def _resolve_category(cls, category_tag: str | None, description: str) -> OpportunityCategory:
        if category_tag:
            tag_clean = category_tag.strip().lower()
            for cat in OpportunityCategory:
                if cat.value == tag_clean:
                    return cat

        desc_lower = description.lower()
        if any(w in desc_lower for w in ("meeting", "calendar", "schedule", "deadline", "event")):
            return OpportunityCategory.SCHEDULE_ALERT
        if any(w in desc_lower for w in ("git", "drift", "diff", "test", "build", "failing")):
            return OpportunityCategory.WORKSPACE_DRIFT
        if any(w in desc_lower for w in ("todo", "reminder", "task", "followup", "note")):
            return OpportunityCategory.TODO_REMINDER
        if any(w in desc_lower for w in ("security", "secret", "credential", "leak", "token")):
            return OpportunityCategory.SECURITY_HYGIENE
        return OpportunityCategory.OPTIMIZATION_PROPOSAL

    @classmethod
    def build_default_manifest(cls) -> HeartbeatManifest:
        """Construct canonical default heartbeat specification."""
        default_items = (
            HeartbeatChecklistItem(
                item_id="hb_chk_1",
                description="Scan workspace git status for uncommitted changes or broken builds",
                target_category=OpportunityCategory.WORKSPACE_DRIFT,
                is_active=True,
            ),
            HeartbeatChecklistItem(
                item_id="hb_chk_2",
                description="Review pending schedule events and meeting preparation",
                target_category=OpportunityCategory.SCHEDULE_ALERT,
                is_active=True,
            ),
            HeartbeatChecklistItem(
                item_id="hb_chk_3",
                description="Evaluate prior turn open tasks and todo reminders",
                target_category=OpportunityCategory.TODO_REMINDER,
                is_active=True,
            ),
        )
        return HeartbeatManifest(
            interval_minutes=cls._DEFAULT_INTERVAL_MINUTES,
            proactivity_level=cls._DEFAULT_LEVEL,
            checklist_items=default_items,
            max_docked_per_hour=cls._DEFAULT_MAX_DOCKED_HOURLY,
            raw_markdown_source="# Canonical Default HEARTBEAT.md",
        )

    @classmethod
    def serialize_manifest(cls, manifest: HeartbeatManifest) -> str:
        """Format a HeartbeatManifest into standard Markdown format."""
        lines = [
            "---",
            f"interval_minutes: {manifest.interval_minutes}",
            f"proactivity_level: {manifest.proactivity_level.value}",
            f"max_docked_per_hour: {manifest.max_docked_per_hour}",
            "---",
            "",
            "# Proactive Heartbeat Checklist",
            "",
        ]
        for it in manifest.checklist_items:
            box = "x" if it.is_active else " "
            lines.append(f"- [{box}] {it.description} (category: {it.target_category.value})")

        return "\n".join(lines) + "\n"
