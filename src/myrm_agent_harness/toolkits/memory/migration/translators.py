"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/translators.py
[INPUT]: Raw competitor files or text payloads in Markdown/JSON formats.
[OUTPUT]: NormalizedMemoryPayload items ready for ingestion and deduplication.
"""

import hashlib
import json
import re
from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.models import (
    CompetitorSourceKind,
    NormalizedMemoryPayload,
)


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]


class UniversalMemoryTranslator:
    """Multi-source cognitive schema normalizer converting competitor data into canonical memory units."""

    def translate_file(
        self, source_kind: CompetitorSourceKind, file_path: str | Path
    ) -> list[NormalizedMemoryPayload]:
        """Read external file and normalize into canonical memory payloads."""
        path = Path(file_path)
        if not path.exists():
            return []
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        return self.translate_raw(
            source_kind=source_kind, raw_text=raw_text, source_id=str(path.name)
        )

    def translate_raw(
        self, source_kind: CompetitorSourceKind, raw_text: str, source_id: str = "raw_input"
    ) -> list[NormalizedMemoryPayload]:
        """Normalize raw serialized text into structured memory payloads based on source kind."""
        stripped = raw_text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                if source_kind == CompetitorSourceKind.OPENCLAW:
                    claw_res = self._parse_openclaw_json(raw_text, source_id)
                    if claw_res:
                        return claw_res
                generic_res = self._parse_generic_json(raw_text, source_kind, source_id)
                if generic_res:
                    return generic_res
            except Exception:
                pass

        return self._parse_markdown_text(raw_text, source_id, source_kind=source_kind)

    def _parse_markdown_text(
        self,
        text: str,
        source_id: str,
        source_kind: CompetitorSourceKind = CompetitorSourceKind.HERMES,
    ) -> list[NormalizedMemoryPayload]:
        payloads: list[NormalizedMemoryPayload] = []
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

            sec_lower = current_section.lower()
            if any(k in sec_lower for k in ("user", "profile", "identity", "persona")):
                layer = "profile"
            elif any(k in sec_lower for k in ("rule", "guideline", "workflow", "instruction")):
                layer = "procedural"
            elif any(k in sec_lower for k in ("event", "log", "history")):
                layer = "episodic"
            else:
                layer = "semantic"

            entry_hash = _compute_hash(content)
            payloads.append(
                NormalizedMemoryPayload(
                    source_kind=source_kind,
                    source_id=f"{source_id}#L{idx + 1}",
                    raw_content=line,
                    normalized_content=content,
                    layer_recommendation=layer,
                    tags=[current_section.replace(" ", "_").lower()],
                    content_hash=entry_hash,
                    provenance_meta={"source": f"{source_kind.value}_text", "section": current_section},
                )
            )

        return payloads

    def _parse_openclaw_json(
        self, text: str, source_id: str
    ) -> list[NormalizedMemoryPayload]:
        payloads: list[NormalizedMemoryPayload] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return payloads

        items: list[dict[str, str | int | float | list[str]]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            if "memories" in data and isinstance(data["memories"], list):
                items = [item for item in data["memories"] if isinstance(item, dict)]
            else:
                for k, v in data.items():
                    items.append({"key": str(k), "content": str(v)})

        for idx, item in enumerate(items):
            content = str(
                item.get("content")
                or item.get("text")
                or item.get("value")
                or item.get("memory")
                or item.get("fact", "")
            ).strip()
            if not content:
                continue

            category = str(item.get("category", "general")).lower()
            layer = "semantic"
            if category in ("user", "profile", "identity"):
                layer = "profile"
            elif category in ("rule", "workflow", "skill"):
                layer = "procedural"

            raw_tags = item.get("tags")
            tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else [category]
            entry_id = str(item.get("id") or item.get("key") or f"{source_id}_{idx}")

            payloads.append(
                NormalizedMemoryPayload(
                    source_kind=CompetitorSourceKind.OPENCLAW,
                    source_id=entry_id,
                    raw_content=json.dumps(item, ensure_ascii=False),
                    normalized_content=content,
                    layer_recommendation=layer,
                    tags=tags,
                    content_hash=_compute_hash(content),
                    provenance_meta={"source": "openclaw_json", "category": category},
                )
            )

        return payloads

    def _parse_generic_json(
        self, text: str, source_kind: CompetitorSourceKind, source_id: str
    ) -> list[NormalizedMemoryPayload]:
        payloads: list[NormalizedMemoryPayload] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return payloads

        items: list[dict[str, str | int | float | list[str]]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            for k, v in data.items():
                items.append({"key": str(k), "content": str(v)})

        for idx, item in enumerate(items):
            content = str(
                item.get("content")
                or item.get("text")
                or item.get("message")
                or item.get("memory")
                or item.get("value", "")
            ).strip()
            if not content:
                continue

            category = str(item.get("category", "general")).lower()
            layer = "semantic"
            if category in ("user", "profile", "identity"):
                layer = "profile"
            elif category in ("rule", "workflow", "instruction"):
                layer = "procedural"

            entry_id = str(item.get("id") or item.get("key") or f"{source_id}_{idx}")
            raw_tags = item.get("tags")
            tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else ([category] if category != "general" else [])

            payloads.append(
                NormalizedMemoryPayload(
                    source_kind=source_kind,
                    source_id=entry_id,
                    raw_content=json.dumps(item, ensure_ascii=False),
                    normalized_content=content,
                    layer_recommendation=layer,
                    tags=tags,
                    content_hash=_compute_hash(content),
                    provenance_meta={"source": source_kind.value},
                )
            )

        return payloads
