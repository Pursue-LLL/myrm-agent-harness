"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory._manager.shared import (
    EpisodicMemory,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
    logger,
)

# ── Path sanitization for safe sharing ─────────────────────────────

_HOME_DIR_UNIX_RE = re.compile(r"(?:/Users/|/home/|/root/)[^\s/\"']+/")
_HOME_DIR_WIN_RE = re.compile(r"[A-Z]:\\Users\\[^\s\\\"']+\\")

_PERSONAL_FIELDS_TO_STRIP = frozenset({
    "access_count", "user_rating", "source_chat_id",
})


def sanitize_paths_for_sharing(text: str) -> str:
    """Replace home directory paths with generic <USER>/ placeholder.

    Only targets user home directories (/Users/xxx/, /home/xxx/, C:\\Users\\xxx\\).
    System paths (/usr/, /etc/, /opt/) are intentionally preserved.
    """
    if not text:
        return text
    text = _HOME_DIR_UNIX_RE.sub("<USER>/", text)
    text = _HOME_DIR_WIN_RE.sub("<USER>\\\\", text)
    return text


def _sanitize_filename(text: str, max_len: int = 60) -> str:
    """Create a safe filename from memory content."""
    clean = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text)
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean[:max_len] if clean else "untitled"


def _extract_tags(metadata: object) -> list[str]:
    """Extract tags from memory metadata dict."""
    tags: list[str] = []
    if isinstance(metadata, dict):
        for k, v in metadata.items():
            if k == "tags" and isinstance(v, str):
                tags.extend(t.strip() for t in v.split(",") if t.strip())
            elif k == "category" and isinstance(v, str):
                tags.append(v)
    return tags


_RendererFn = Callable[
    [dict[str, object], str, str, str, str, str],
    str,
]


def _list_to_yaml_inline(items: list[object]) -> str:
    """Format a list as YAML inline sequence: [a, b, c]."""
    return f"[{', '.join(str(i) for i in items)}]"


def _yaml_safe_value(value: object) -> str:
    """Ensure a scalar value is safe for YAML frontmatter (no broken lines)."""
    s = str(value)
    if "\n" in s or "\r" in s:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        return f'"{escaped}"'
    return s


def _common_fields(memory_dict: dict[str, object]) -> tuple[str, str, str, str, str]:
    """Extract fields shared by all memory types."""
    mem_id = str(memory_dict.get("id", ""))
    content = str(memory_dict.get("content", ""))
    created_at = str(memory_dict.get("created_at", ""))
    updated_at = str(memory_dict.get("updated_at", ""))
    tags = _extract_tags(memory_dict.get("metadata", {}))
    tags_line = f"\ntags: [{', '.join(tags)}]" if tags else ""
    return mem_id, content, created_at, updated_at, tags_line


def _memory_to_markdown(memory_dict: dict[str, object], memory_type: str) -> str:
    """Convert a single memory dict to Markdown with YAML frontmatter.

    Each memory type has a dedicated renderer that includes its unique
    metadata fields in the frontmatter.  Unknown types fall back to a
    generic id/type/created_at/updated_at template.
    """
    mem_id, content, created_at, updated_at, tags_line = _common_fields(memory_dict)

    renderer = _TYPE_RENDERERS.get(memory_type)
    if renderer:
        return renderer(memory_dict, mem_id, content, created_at, updated_at, tags_line)

    frontmatter = (
        f"---\n"
        f"id: {mem_id}\n"
        f"type: {memory_type}\n"
        f"created_at: {created_at}\n"
        f"updated_at: {updated_at}{tags_line}\n"
        f"---\n"
    )
    return f"{frontmatter}\n{content}\n"


def _procedural_to_markdown(
    d: dict[str, object],
    mem_id: str,
    content: str,
    created_at: str,
    updated_at: str,
    tags_line: str,
) -> str:
    """Render ProceduralMemory with full rule structure in frontmatter and body."""
    trigger = d.get("trigger", "")
    action = d.get("action", "")
    lines = [
        "---",
        f"id: {mem_id}",
        "type: procedural",
        f"trigger: {_yaml_safe_value(trigger)}",
        f"action: {_yaml_safe_value(action)}",
        f"priority: {d.get('priority', 0)}",
        f"source: {d.get('source', '')}",
        f"status: {d.get('status', '')}",
    ]
    language = d.get("language")
    if language:
        lines.append(f"language: {language}")
    tool_name = d.get("tool_name")
    if tool_name:
        lines.append(f"tool_name: {tool_name}")
        lines.append(f"tool_rule_priority: {d.get('tool_rule_priority', 'normal')}")
    if d.get("pinned"):
        lines.append("pinned: true")
    lines.append(f"access_count: {d.get('access_count', 0)}")
    lines.append(f"user_rating: {d.get('user_rating', 0.5)}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}{tags_line}")
    lines.append("---")

    body_parts: list[str] = []
    reasoning = d.get("reasoning")
    if reasoning:
        body_parts.append(f"## Reasoning\n\n{reasoning}")
    application = d.get("application")
    if application:
        body_parts.append(f"## Application\n\n{application}")
    body_parts.append(content)

    return "\n".join(lines) + "\n\n" + "\n\n".join(body_parts) + "\n"


def _semantic_to_markdown(
    d: dict[str, object],
    mem_id: str,
    content: str,
    created_at: str,
    updated_at: str,
    tags_line: str,
) -> str:
    """Render SemanticMemory with importance/confidence/preference metadata."""
    lines = [
        "---",
        f"id: {mem_id}",
        "type: semantic",
        f"importance: {d.get('importance', 0.5)}",
        f"confidence: {d.get('confidence', 1.0)}",
        f"language: {d.get('language', 'en')}",
    ]
    pref = d.get("preference_type")
    if pref:
        lines.append(f"preference_type: {pref}")
    src = d.get("source_chat_id")
    if src:
        lines.append(f"source_chat_id: {src}")
    sem_tags = d.get("tags")
    if isinstance(sem_tags, list) and sem_tags:
        lines.append(f"tags: {_list_to_yaml_inline(sem_tags)}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}{tags_line}")
    lines.append("---")
    return "\n".join(lines) + f"\n\n{content}\n"


def _episodic_to_markdown(
    d: dict[str, object],
    mem_id: str,
    content: str,
    created_at: str,
    updated_at: str,
    tags_line: str,
) -> str:
    """Render EpisodicMemory with event_type/importance/entities metadata."""
    lines = [
        "---",
        f"id: {mem_id}",
        "type: episodic",
        f"event_type: {d.get('event_type', 'conversation')}",
        f"importance: {d.get('importance', 0.5)}",
        f"language: {d.get('language', 'en')}",
    ]
    entities = d.get("related_entities")
    if isinstance(entities, list) and entities:
        lines.append(f"related_entities: {_list_to_yaml_inline(entities)}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}{tags_line}")
    lines.append("---")
    return "\n".join(lines) + f"\n\n{content}\n"


def _conversation_to_markdown(
    d: dict[str, object],
    mem_id: str,
    content: str,
    created_at: str,
    updated_at: str,
    tags_line: str,
) -> str:
    """Render ConversationMemory preserving raw_exchange in body."""
    lines = [
        "---",
        f"id: {mem_id}",
        "type: conversation",
        f"importance: {d.get('importance', 0.5)}",
        f"language: {d.get('language', 'en')}",
    ]
    for opt_key in ("project_id", "topic_id", "source_chat_id"):
        val = d.get(opt_key)
        if val:
            lines.append(f"{opt_key}: {val}")
    entities = d.get("related_entities")
    if isinstance(entities, list) and entities:
        lines.append(f"related_entities: {_list_to_yaml_inline(entities)}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}{tags_line}")
    lines.append("---")

    body_parts: list[str] = [f"## Summary\n\n{content}"]
    raw = d.get("raw_exchange")
    if raw:
        body_parts.append(f"## Original Exchange\n\n{raw}")
    return "\n".join(lines) + "\n\n" + "\n\n".join(body_parts) + "\n"


def _claim_to_markdown(
    d: dict[str, object],
    mem_id: str,
    content: str,
    created_at: str,
    updated_at: str,
    tags_line: str,
) -> str:
    """Render ClaimMemory with evidence/confidence metadata."""
    lines = [
        "---",
        f"id: {mem_id}",
        "type: claim",
        f"claim_key: {_yaml_safe_value(d.get('claim_key', ''))}",
        f"title: {_yaml_safe_value(d.get('title', ''))}",
        f"evidence_count: {d.get('evidence_count', 0)}",
        f"confidence: {d.get('confidence', 0.75)}",
        f"freshness: {d.get('freshness', 'stale')}",
        f"created_at: {created_at}",
        f"updated_at: {updated_at}{tags_line}",
        "---",
    ]
    body_parts: list[str] = []
    claim_text = d.get("claim_text")
    if claim_text:
        body_parts.append(f"## Claim\n\n{claim_text}")
    summary = d.get("model_summary")
    if summary:
        body_parts.append(f"## Summary\n\n{summary}")
    if content and content not in (claim_text, summary):
        body_parts.append(content)
    return "\n".join(lines) + "\n\n" + ("\n\n".join(body_parts) if body_parts else content) + "\n"


def _integration_to_markdown(
    d: dict[str, object],
    mem_id: str,
    content: str,
    created_at: str,
    updated_at: str,
    tags_line: str,
) -> str:
    """Render IntegrationMemory with provider/source metadata."""
    lines = [
        "---",
        f"id: {mem_id}",
        "type: integration",
        f"provider: {_yaml_safe_value(d.get('provider', ''))}",
        f"title: {_yaml_safe_value(d.get('title', ''))}",
        f"importance: {d.get('importance', 0.5)}",
    ]
    observed = d.get("observed_at")
    if observed:
        lines.append(f"observed_at: {observed}")
    int_tags = d.get("tags")
    if isinstance(int_tags, list) and int_tags:
        lines.append(f"tags: {_list_to_yaml_inline(int_tags)}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}{tags_line}")
    lines.append("---")

    body_parts: list[str] = []
    summary = d.get("summary")
    if summary:
        body_parts.append(f"## Summary\n\n{summary}")
    if content and content != summary:
        body_parts.append(content)
    return "\n".join(lines) + "\n\n" + ("\n\n".join(body_parts) if body_parts else content) + "\n"


_TYPE_RENDERERS: dict[str, _RendererFn] = {
    "procedural": _procedural_to_markdown,
    "semantic": _semantic_to_markdown,
    "episodic": _episodic_to_markdown,
    "conversation": _conversation_to_markdown,
    "claim": _claim_to_markdown,
    "integration": _integration_to_markdown,
}


class MemoryManagerImportExportMixin:
    # ── Export / Import ──

    async def export_markdown(
        self,
        target_dir: str | Path,
        *,
        since_ts: datetime | None = None,
        agent_id: str | None = None,
        memory_types: list[MemoryType] | None = None,
    ) -> dict[str, int]:
        """Export memories as Markdown files organized by type.

        Each memory becomes a `.md` file with type-specific YAML frontmatter
        inside a subdirectory named after the memory type.

        Args:
            target_dir: Root directory for exported files.
            since_ts: Only export memories created/updated after this timestamp.
            agent_id: Only export memories belonging to this agent (via scope).
            memory_types: Only export these memory types. None = all types.

        Returns:
            Dict with export counts per memory type.
        """
        target = Path(target_dir)
        counts: dict[str, int] = {}

        data = await self.export_all()
        allowed_types = {t.value for t in memory_types} if memory_types else None

        for type_name, entries in data.items():
            if allowed_types and type_name not in allowed_types:
                continue
            type_dir = target / type_name
            type_dir.mkdir(parents=True, exist_ok=True)

            exported = 0
            id_to_path: dict[str, Path] = {}

            for existing_file in type_dir.glob("*.md"):
                try:
                    text = existing_file.read_text(encoding="utf-8")
                    id_match = re.search(r"^id:\s*(.+)$", text, re.MULTILINE)
                    if id_match:
                        id_to_path[id_match.group(1).strip()] = existing_file
                except OSError:
                    pass

            for entry in entries:
                mem_id = str(entry.get("id", ""))

                if since_ts:
                    updated = entry.get("updated_at") or entry.get("created_at")
                    if updated and isinstance(updated, str):
                        try:
                            entry_ts = datetime.fromisoformat(updated)
                            if entry_ts < since_ts:
                                continue
                        except (ValueError, TypeError):
                            pass

                if agent_id:
                    scope = entry.get("scope")
                    if isinstance(scope, dict):
                        ns_list = scope.get("namespaces", [])
                        if not any(agent_id in str(ns) for ns in ns_list):
                            continue

                content = str(entry.get("content", ""))
                md_content = _memory_to_markdown(entry, type_name)

                if mem_id in id_to_path:
                    try:
                        id_to_path[mem_id].write_text(md_content, encoding="utf-8")
                        exported += 1
                    except OSError:
                        pass
                else:
                    filename = f"{_sanitize_filename(content)}_{mem_id[:8]}.md"
                    file_path = type_dir / filename
                    file_path.write_text(md_content, encoding="utf-8")
                    id_to_path[mem_id] = file_path
                    exported += 1

            counts[type_name] = exported

        return counts

    async def export_rules_safe(
        self,
        *,
        agent_id: str | None = None,
        rule_ids: list[str] | None = None,
        output_format: str = "markdown",
    ) -> list[dict[str, object]]:
        """Export ProceduralMemory rules with privacy sanitization for safe sharing.

        Applies path anonymization and credential redaction, strips personal
        metadata fields (access_count, user_rating, source_chat_id).

        Args:
            agent_id: Only export rules belonging to this agent.
            rule_ids: Only export these specific rule IDs. None = all rules.
            output_format: "markdown" or "json".

        Returns:
            List of sanitized rule dicts (each with "id", "content", and
            "rendered" key containing the final markdown/json string).
        """
        from myrm_agent_harness.core.security.redact import redact_sensitive_text

        data = await self.export_all()
        procedural_entries = data.get(MemoryType.PROCEDURAL.value, [])

        results: list[dict[str, object]] = []
        for entry in procedural_entries:
            mem_id = str(entry.get("id", ""))

            if rule_ids and mem_id not in rule_ids:
                continue

            if agent_id:
                scope = entry.get("scope")
                if isinstance(scope, dict):
                    ns_list = scope.get("namespaces", [])
                    if not any(agent_id in str(ns) for ns in ns_list):
                        continue

            sanitized = {
                k: v for k, v in entry.items()
                if k not in _PERSONAL_FIELDS_TO_STRIP and k != "embedding"
            }

            for field in ("content", "trigger", "action", "reasoning", "application"):
                val = sanitized.get(field)
                if isinstance(val, str) and val:
                    sanitized[field] = sanitize_paths_for_sharing(
                        redact_sensitive_text(val)
                    )

            if output_format == "json":
                rendered = json.dumps(sanitized, ensure_ascii=False, indent=2)
            else:
                rendered = _memory_to_markdown(sanitized, "procedural")

            results.append({
                "id": mem_id,
                "content": str(sanitized.get("content", "")),
                "rendered": rendered,
            })

        return results

    async def export_all(self) -> dict[str, list[dict[str, object]]]:
        """Export all memories as serializable dicts (excludes embeddings for portability).

        Returns:
            Dict keyed by memory type with lists of serialized memory objects.
        """
        result: dict[str, list[dict[str, object]]] = {}

        for mem_type in MemoryType:
            if mem_type == MemoryType.TASK_DIGEST:
                continue
            try:
                memories = await self.list_memories(mem_type, limit=10000, include_archived=True)
                if memories:
                    serialized: list[dict[str, object]] = []
                    for m in memories:
                        data = m.model_dump(mode="json", exclude={"embedding"})
                        serialized.append(data)
                    result[mem_type.value] = serialized
            except Exception as e:
                logger.warning("Export failed for %s: %s", mem_type.value, e)

        return result

    async def import_memories(
        self, data: dict[str, list[dict[str, object]]], *, skip_duplicates: bool = True
    ) -> dict[str, int]:
        """Import memories from exported data, recomputing embeddings.

        Deduplication happens via ``store_batch`` when ``skip_duplicates`` is True
        and a deduplicator is configured. Profile entries are upserted via the
        relational backend directly.

        Args:
            data: Dict keyed by memory type with lists of serialized memory objects.
            skip_duplicates: When True (default), deduplicator filters duplicates.

        Returns:
            Dict with import counts per memory type.
        """
        counts: dict[str, int] = {}

        type_parsers: dict[str, type[SemanticMemory | EpisodicMemory | ProceduralMemory]] = {
            MemoryType.SEMANTIC.value: SemanticMemory,
            MemoryType.EPISODIC.value: EpisodicMemory,
            MemoryType.PROCEDURAL.value: ProceduralMemory,
        }

        saved_dedup = self._deduplicator
        if not skip_duplicates:
            self._deduplicator = None

        try:
            for type_name, entries in data.items():
                parser = type_parsers.get(type_name)
                if parser is None:
                    if type_name == MemoryType.PROFILE.value and self._relational:
                        imported = 0
                        for entry in entries:
                            try:
                                meta = entry.get("metadata") or {}
                                key = str(entry.get("key", "") or meta.get("key", ""))
                                value = entry.get("value", "") or meta.get("value", "")
                                if key:
                                    await self._relational.set_profile(key, str(value), scope=self._scope)
                                    imported += 1
                            except Exception as e:
                                logger.warning("Import profile entry failed: %s", e)
                        counts[type_name] = imported
                    continue

                memories: list[SemanticMemory | EpisodicMemory | ProceduralMemory] = []
                for entry in entries:
                    try:
                        clean = {k: v for k, v in entry.items() if k not in ("id", "embedding")}
                        mem = parser.model_validate(clean)
                        memories.append(mem)
                    except Exception as e:
                        logger.warning("Import parse failed for %s entry: %s", type_name, e)

                if memories:
                    try:
                        stored = await self.store_batch(memories)
                        counts[type_name] = len(stored)
                    except Exception as e:
                        logger.warning("Import batch store failed for %s: %s", type_name, e)
                        counts[type_name] = 0
                else:
                    counts[type_name] = 0
        finally:
            self._deduplicator = saved_dedup

        return counts
