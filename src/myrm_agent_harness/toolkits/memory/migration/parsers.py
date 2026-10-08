"""Multi-platform memory parsing matrix.

[POS]
Adaptive parsing engines for extracting structured cognitive memory units from
OpenClaw, Hermes, ChatGPT exports, Claude projects, and generic Markdown note trees.

[INPUT]
- hashlib, json, pathlib.Path, re, typing
- .models.ExtractedMemoryUnit, .models.MigrationSourceType
- .security_guard.MigrationSecurityGuard

[OUTPUT]
- MultiPlatformParserMatrix, OpenClawParser, HermesParser, ChatExportParser, MarkdownTreeParser
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

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
        layer = "semantic"

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
                            layer = val

        lines = content_body.strip().splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip().lstrip("-* ")
            if len(stripped) < 3 or stripped.startswith("#"):
                continue

            cleansed = guard.sanitize_text(stripped)
            units.append(
                ExtractedMemoryUnit(
                    source_type=MigrationSourceType.HERMES,
                    source_id=f"{source_id}#L{idx + 1}",
                    raw_snippet=line,
                    normalized_text=cleansed,
                    layer=layer,
                    tags=list(set(tags)),
                    content_hash=_hash_content(cleansed),
                    provenance={"format": "hermes_md"},
                )
            )
        return units


class ChatExportParser:
    """Parses ChatGPT and Claude conversation export JSON dumps."""

    def parse(
        self,
        raw_text: str,
        source_id: str,
        guard: MigrationSecurityGuard,
    ) -> list[ExtractedMemoryUnit]:
        units: list[ExtractedMemoryUnit] = []
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return units

        conversations: list[dict[str, str | list[dict[str, str]]]] = []
        if isinstance(data, list):
            conversations = [c for c in data if isinstance(c, dict)]
        elif isinstance(data, dict):
            conversations = [data]

        for conv_idx, conv in enumerate(conversations):
            title = str(conv.get("title", f"Chat {conv_idx + 1}"))
            mapping = conv.get("mapping")

            # Format 1: mapping node tree
            if isinstance(mapping, dict):
                for node_id, node in mapping.items():
                    if not isinstance(node, dict):
                        continue
                    msg = node.get("message")
                    if not isinstance(msg, dict):
                        continue
                    author = msg.get("author", {})
                    role = author.get("role", "") if isinstance(author, dict) else ""
                    if role not in ("assistant", "user"):
                        continue
                    content = msg.get("content", {})
                    parts = content.get("parts", []) if isinstance(content, dict) else []
                    for part_idx, part in enumerate(parts):
                        if isinstance(part, str) and len(part.strip()) >= 20:
                            cleansed = guard.sanitize_text(part)
                            units.append(
                                ExtractedMemoryUnit(
                                    source_type=MigrationSourceType.CHATGPT_EXPORT,
                                    source_id=f"{title}_{node_id}_{part_idx}",
                                    raw_snippet=part[:200],
                                    normalized_text=cleansed,
                                    layer="episodic" if role == "user" else "semantic",
                                    tags=["chat_export", role],
                                    content_hash=_hash_content(cleansed),
                                    provenance={"title": title, "role": role},
                                )
                            )

            # Format 2: linear messages list
            messages = conv.get("messages")
            if isinstance(messages, list):
                for m_idx, m in enumerate(messages):
                    if not isinstance(m, dict):
                        continue
                    role = str(m.get("role", "unknown"))
                    text = str(m.get("content", "")).strip()
                    if len(text) >= 20:
                        cleansed = guard.sanitize_text(text)
                        units.append(
                            ExtractedMemoryUnit(
                                source_type=MigrationSourceType.CHATGPT_EXPORT,
                                source_id=f"{title}_m{m_idx}",
                                raw_snippet=text[:200],
                                normalized_text=cleansed,
                                layer="episodic" if role == "user" else "semantic",
                                tags=["chat_export", role],
                                content_hash=_hash_content(cleansed),
                                provenance={"title": title, "role": role},
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


class MultiPlatformParserMatrix:
    """Unified facade intelligently dispatching artifacts to appropriate platform parsers."""

    def __init__(self, security_guard: MigrationSecurityGuard | None = None) -> None:
        self._guard = security_guard or MigrationSecurityGuard()
        self._openclaw_parser = OpenClawParser()
        self._hermes_parser = HermesParser()
        self._chat_parser = ChatExportParser()
        self._md_parser = MarkdownTreeParser()

    def parse_payload(
        self,
        source_type: MigrationSourceType,
        raw_content: str,
        source_id: str = "raw_input",
    ) -> list[ExtractedMemoryUnit]:
        """Dispatch in-memory text payload to corresponding parser."""
        if source_type == MigrationSourceType.OPENCLAW:
            return self._openclaw_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.HERMES:
            return self._hermes_parser.parse(raw_content, source_id, self._guard)
        if source_type in (MigrationSourceType.CHATGPT_EXPORT, MigrationSourceType.CLAUDE_PROJECT):
            return self._chat_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.MARKDOWN_TREE:
            return self._md_parser.parse(raw_content, source_id, self._guard)

        # Fallback to OpenClaw auto JSON/MD parser
        return self._openclaw_parser.parse(raw_content, source_id, self._guard)

    def parse_file(
        self,
        source_type: MigrationSourceType,
        file_path: Path | str,
    ) -> list[ExtractedMemoryUnit]:
        """Validate safety bounds and parse external file."""
        path = Path(file_path)
        if not path.is_file():
            return []

        self._guard.validate_file(path)
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        return self.parse_payload(source_type, raw_text, source_id=path.name)
