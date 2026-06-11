"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory._manager.shared import (
    EpisodicMemory,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
    logger,
)


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


def _memory_to_markdown(memory_dict: dict[str, object], memory_type: str) -> str:
    """Convert a single memory dict to Markdown with YAML frontmatter.

    ProceduralMemory gets enriched output with trigger/action structure
    and rule metadata in frontmatter. Other types use content-only body.
    """
    mem_id = memory_dict.get("id", "")
    content = str(memory_dict.get("content", ""))
    created_at = memory_dict.get("created_at", "")
    updated_at = memory_dict.get("updated_at", "")
    tags = _extract_tags(memory_dict.get("metadata", {}))
    tags_line = f"\ntags: [{', '.join(tags)}]" if tags else ""

    if memory_type == "procedural":
        return _procedural_to_markdown(memory_dict, mem_id, content, created_at, updated_at, tags_line)

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
    mem_id: object,
    content: str,
    created_at: object,
    updated_at: object,
    tags_line: str,
) -> str:
    """Render ProceduralMemory with full rule structure in frontmatter and body."""
    trigger = d.get("trigger", "")
    action = d.get("action", "")
    lines = [
        "---",
        f"id: {mem_id}",
        "type: procedural",
        f"trigger: {trigger}",
        f"action: {action}",
        f"priority: {d.get('priority', 0)}",
        f"source: {d.get('source', '')}",
        f"status: {d.get('status', '')}",
    ]
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


class MemoryManagerImportExportMixin:
    # ── Export / Import ──

    async def export_markdown(
        self,
        target_dir: str | Path,
        *,
        since_ts: datetime | None = None,
        agent_id: str | None = None,
    ) -> dict[str, int]:
        """Export memories as Markdown files organized by type.

        Each memory becomes a `.md` file with YAML frontmatter (id, type,
        created_at, tags) inside a subdirectory named after the memory type.

        Args:
            target_dir: Root directory for exported files.
            since_ts: Only export memories created/updated after this timestamp.
            agent_id: Only export memories belonging to this agent (via scope).

        Returns:
            Dict with export counts per memory type.
        """
        target = Path(target_dir)
        counts: dict[str, int] = {}

        data = await self.export_all()

        for type_name, entries in data.items():
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
