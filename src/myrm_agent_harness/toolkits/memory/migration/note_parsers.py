"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/note_parsers.py
[INPUT]: OpenClaw layouts, Hermes memory files, and generic hierarchical Markdown note trees.
[OUTPUT]: OpenClawParser, HermesParser, and MarkdownTreeParser extracting ExtractedMemoryUnit facts.
"""

from __future__ import annotations

import hashlib
import json
import re

from myrm_agent_harness.toolkits.memory.migration.models import (
    ExtractedMemoryUnit,
    MigrationSourceType,
)
from myrm_agent_harness.toolkits.memory.migration.security_guard import (
    MigrationSecurityGuard,
)


def _hash_content(content: str) -> str:
    """Deterministic 16-character SHA-256 fingerprint."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]


class OpenClawParser:
    """Parses OpenClaw native memory layouts (MEMORY.md, USER.md, memory/*.md, JSON)."""

    def parse(
        self,
        raw_text: str,
        source_id: str,
        security_guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        """Extract memory items from OpenClaw raw markdown or JSON text."""
        stripped = raw_text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            return self._parse_json(stripped, source_id, security_guard)
        return self._parse_markdown(raw_text, source_id, security_guard)

    def _parse_json(
        self,
        text: str,
        source_id: str,
        guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        units: list[ExtractedMemoryUnit] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return units

        items: list[dict[str, str | int | float | list[str] | dict[str, str]]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            if "memories" in data and isinstance(data["memories"], list):
                items = [item for item in data["memories"] if isinstance(item, dict)]
            else:
                for k, v in data.items():
                    items.append({"id": str(k), "text": str(v)})

        for idx, item in enumerate(items):
            raw_text = str(
                item.get("text")
                or item.get("content")
                or item.get("memory")
                or item.get("value")
                or item.get("fact", "")
            ).strip()
            if not raw_text or len(raw_text) < 3:
                continue

            cleansed = guard.sanitize_text(raw_text)
            category = str(item.get("category", "general")).lower()
            layer = "semantic"
            if category in ("user", "profile", "identity", "persona"):
                layer = "profile"
            elif category in ("rule", "workflow", "guideline", "skill"):
                layer = "procedural"
            elif category in ("event", "log", "conversation"):
                layer = "episodic"

            raw_tags = item.get("tags")
            tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else [category]
            entry_id = str(item.get("id") or item.get("key") or f"{source_id}_{idx}")

            units.append(
                ExtractedMemoryUnit(
                    source_type=MigrationSourceType.OPENCLAW,
                    source_id=entry_id,
                    raw_snippet=raw_text,
                    normalized_text=cleansed,
                    layer=layer,
                    tags=tags,
                    content_hash=_hash_content(cleansed),
                    provenance={"format": "openclaw_json", "category": category},
                )
            )
        return units

    def _parse_markdown(
        self,
        text: str,
        source_id: str,
        guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        units: list[ExtractedMemoryUnit] = []
        is_user_file = "user" in source_id.lower()
        current_section = "general"
        lines = text.splitlines()

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("#"):
                current_section = re.sub(r"^#+\s*", "", stripped).strip()
                continue

            content = stripped.lstrip("-* ").strip()
            if len(content) < 3:
                continue

            cleansed = guard.sanitize_text(content)
            layer = "profile" if is_user_file else self._infer_layer(current_section)

            units.append(
                ExtractedMemoryUnit(
                    source_type=MigrationSourceType.OPENCLAW,
                    source_id=f"{source_id}#L{idx + 1}",
                    raw_snippet=line,
                    normalized_text=cleansed,
                    layer=layer,
                    tags=[current_section.replace(" ", "_").lower()],
                    content_hash=_hash_content(cleansed),
                    provenance={"format": "openclaw_md", "section": current_section},
                )
            )
        return units

    def _infer_layer(self, section: str) -> str:
        sec = section.lower()
        if any(k in sec for k in ("profile", "user", "preference", "identity")):
            return "profile"
        if any(k in sec for k in ("rule", "workflow", "instruction", "skill")):
            return "procedural"
        if any(k in sec for k in ("event", "history", "milestone")):
            return "episodic"
        return "semantic"


class HermesParser:
    """Parses Hermes memory files (.hermes/memories/*.md with optional frontmatter)."""

    def parse(
        self,
        raw_text: str,
        source_id: str,
        guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        units: list[ExtractedMemoryUnit] = []
        content_body = raw_text
        tags: list[str] = ["hermes"]
        explicit_layer: str | None = None

        # Check frontmatter
        if raw_text.startswith("---"):
            parts = raw_text.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                content_body = parts[2]
                for fm_line in frontmatter.splitlines():
                    if "tags:" in fm_line:
                        tags.extend(re.findall(r"[\w-]+", fm_line.replace("tags:", "")))
                    if "type:" in fm_line or "layer:" in fm_line:
                        val = fm_line.split(":")[-1].strip().lower()
                        if val in ("profile", "semantic", "procedural", "episodic"):
                            explicit_layer = val

        current_section = "general"
        lines = content_body.strip().splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("#"):
                current_section = re.sub(r"^#+\s*", "", stripped).strip()
                continue

            content = stripped.lstrip("-* ").strip()
            if len(content) < 3:
                continue

            if explicit_layer:
                item_layer = explicit_layer
            else:
                sec_lower = current_section.lower()
                if any(k in sec_lower for k in ("user", "profile", "identity", "persona")):
                    item_layer = "profile"
                elif any(k in sec_lower for k in ("rule", "guideline", "workflow", "instruction")):
                    item_layer = "procedural"
                elif any(k in sec_lower for k in ("event", "log", "history")):
                    item_layer = "episodic"
                else:
                    item_layer = "semantic"

            cleansed = guard.sanitize_text(content)
            item_tags = list(set([*tags, current_section.replace(" ", "_").lower()]))
            units.append(
                ExtractedMemoryUnit(
                    source_type=MigrationSourceType.HERMES,
                    source_id=f"{source_id}#L{idx + 1}",
                    raw_snippet=line,
                    normalized_text=cleansed,
                    layer=item_layer,
                    tags=item_tags,
                    content_hash=_hash_content(cleansed),
                    provenance={"format": "hermes_md", "section": current_section},
                )
            )
        return units


class MarkdownTreeParser:
    """Parses generic hierarchical Markdown personal notes and knowledge bases."""

    def parse(
        self,
        raw_text: str,
        source_id: str,
        guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        units: list[ExtractedMemoryUnit] = []
        current_heading = "General"
        lines = raw_text.splitlines()

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("#"):
                current_heading = re.sub(r"^#+\s*", "", stripped).strip()
                continue

            content = stripped.lstrip("-* ").strip()
            if len(content) < 5:
                continue

            cleansed = guard.sanitize_text(content)
            units.append(
                ExtractedMemoryUnit(
                    source_type=MigrationSourceType.MARKDOWN_TREE,
                    source_id=f"{source_id}#L{idx + 1}",
                    raw_snippet=line,
                    normalized_text=cleansed,
                    layer="semantic",
                    tags=[current_heading.replace(" ", "_").lower()],
                    content_hash=_hash_content(cleansed),
                    provenance={"section": current_heading},
                )
            )
        return units
