"""Multi-source cognitive schema normalizer converting competitor data into canonical memory units.

[POS]
src/myrm_agent_harness/toolkits/memory/migration/translators.py
Adapts diverse external formats (OpenClaw, Hermes, MemOS, ChatGPT, Claude Projects,
generic JSON/Markdown) into canonical NormalizedMemoryPayload units with 3-layer classification.

[INPUT]
- hashlib, json, re, pathlib.Path
- toolkits.memory.migration.models::CompetitorSourceKind, NormalizedMemoryPayload

[OUTPUT]
- UniversalMemoryTranslator: Main multi-platform translation engine.
"""

from __future__ import annotations

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
                elif source_kind == CompetitorSourceKind.MEMOS:
                    memos_res = self._parse_memos_json(raw_text, source_id)
                    if memos_res:
                        return memos_res
                elif source_kind == CompetitorSourceKind.CHATGPT_EXPORT:
                    gpt_res = self._parse_chatgpt_json(raw_text, source_id)
                    if gpt_res:
                        return gpt_res
                elif source_kind == CompetitorSourceKind.CLAUDE_PROJECT:
                    claude_res = self._parse_claude_project_json(raw_text, source_id)
                    if claude_res:
                        return claude_res

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

    def _parse_memos_json(
        self, text: str, source_id: str
    ) -> list[NormalizedMemoryPayload]:
        """Parse MemOS graph JSON format containing entities, concepts, or triples."""
        payloads: list[NormalizedMemoryPayload] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return payloads

        if not isinstance(data, dict):
            return payloads

        # 1. Parse entities / nodes
        nodes = data.get("nodes") or data.get("entities") or []
        if isinstance(nodes, list):
            for idx, node in enumerate(nodes):
                if not isinstance(node, dict):
                    continue
                name = str(node.get("name") or node.get("label") or node.get("title", "")).strip()
                desc = str(node.get("description") or node.get("content") or "").strip()
                content = f"{name}: {desc}" if desc else name
                if not content:
                    continue

                entity_type = str(node.get("type", "semantic")).lower()
                layer = "profile" if "user" in entity_type or "persona" in entity_type else "semantic"
                node_id = str(node.get("id") or f"{source_id}_node_{idx}")
                payloads.append(
                    NormalizedMemoryPayload(
                        source_kind=CompetitorSourceKind.MEMOS,
                        source_id=node_id,
                        raw_content=json.dumps(node, ensure_ascii=False),
                        normalized_content=content,
                        layer_recommendation=layer,
                        tags=["memos_entity", entity_type],
                        content_hash=_compute_hash(content),
                        provenance_meta={"source": "memos_graph", "entity_type": entity_type},
                    )
                )

        # 2. Parse edges / triples
        triples = data.get("triples") or data.get("relations") or []
        if isinstance(triples, list):
            for idx, triple in enumerate(triples):
                if not isinstance(triple, dict):
                    continue
                subj = str(triple.get("subject") or triple.get("head", "")).strip()
                pred = str(triple.get("predicate") or triple.get("relation", "")).strip()
                obj = str(triple.get("object") or triple.get("tail", "")).strip()
                if not (subj and pred and obj):
                    continue
                content = f"{subj} {pred} {obj}"
                triple_id = str(triple.get("id") or f"{source_id}_rel_{idx}")
                payloads.append(
                    NormalizedMemoryPayload(
                        source_kind=CompetitorSourceKind.MEMOS,
                        source_id=triple_id,
                        raw_content=json.dumps(triple, ensure_ascii=False),
                        normalized_content=content,
                        layer_recommendation="semantic",
                        tags=["memos_relation", pred.lower()],
                        content_hash=_compute_hash(content),
                        provenance_meta={"source": "memos_triple", "relation": pred},
                    )
                )

        return payloads

    def _parse_chatgpt_json(
        self, text: str, source_id: str
    ) -> list[NormalizedMemoryPayload]:
        """Parse ChatGPT exported conversations.json or user preferences structure."""
        payloads: list[NormalizedMemoryPayload] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return payloads

        conv_list: list[dict[str, str | dict[str, str | int]]] = []
        if isinstance(data, list):
            conv_list = [c for c in data if isinstance(c, dict)]
        elif isinstance(data, dict):
            conv_list = [data]

        for conv_idx, conv in enumerate(conv_list):
            title = str(conv.get("title", f"Conversation_{conv_idx}")).strip()
            # Check for custom instructions
            instructions = conv.get("custom_instructions") or conv.get("instructions")
            if isinstance(instructions, str) and instructions.strip():
                content = instructions.strip()
                payloads.append(
                    NormalizedMemoryPayload(
                        source_kind=CompetitorSourceKind.CHATGPT_EXPORT,
                        source_id=f"{source_id}_inst_{conv_idx}",
                        raw_content=content,
                        normalized_content=content,
                        layer_recommendation="profile",
                        tags=["chatgpt_instructions", "user_profile"],
                        content_hash=_compute_hash(content),
                        provenance_meta={"source": "chatgpt_instructions", "conversation_title": title},
                    )
                )

            # Check mapping for key message turns
            mapping = conv.get("mapping")
            if isinstance(mapping, dict):
                for node_id, node_data in mapping.items():
                    if not isinstance(node_data, dict):
                        continue
                    message = node_data.get("message")
                    if not isinstance(message, dict):
                        continue
                    author = message.get("author")
                    role = author.get("role", "") if isinstance(author, dict) else ""
                    content_obj = message.get("content")
                    parts = content_obj.get("parts", []) if isinstance(content_obj, dict) else []
                    text_parts = [str(p).strip() for p in parts if isinstance(p, str) and p.strip()]
                    full_text = " ".join(text_parts).strip()
                    if len(full_text) < 10:
                        continue

                    # Filter out purely short acknowledgements
                    if full_text.lower() in ("ok", "yes", "thanks", "好的", "收到"):
                        continue

                    layer = "profile" if role == "user" and any(k in full_text for k in ("我喜欢", "我是", "我需要", "偏好", "记住")) else "episodic"
                    payloads.append(
                        NormalizedMemoryPayload(
                            source_kind=CompetitorSourceKind.CHATGPT_EXPORT,
                            source_id=f"{source_id}_{node_id}",
                            raw_content=full_text,
                            normalized_content=full_text,
                            layer_recommendation=layer,
                            tags=["chatgpt_chat", role],
                            content_hash=_compute_hash(full_text),
                            provenance_meta={"role": role, "conversation": title},
                        )
                    )

        return payloads

    def _parse_claude_project_json(
        self, text: str, source_id: str
    ) -> list[NormalizedMemoryPayload]:
        """Parse Claude Project export format containing custom instructions and project knowledge."""
        payloads: list[NormalizedMemoryPayload] = []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return payloads

        if not isinstance(data, dict):
            return payloads

        # 1. Project instructions
        prompt = str(data.get("prompt_template") or data.get("custom_instructions") or "").strip()
        if prompt:
            payloads.append(
                NormalizedMemoryPayload(
                    source_kind=CompetitorSourceKind.CLAUDE_PROJECT,
                    source_id=f"{source_id}_prompt",
                    raw_content=prompt,
                    normalized_content=prompt,
                    layer_recommendation="procedural",
                    tags=["claude_project", "instructions"],
                    content_hash=_compute_hash(prompt),
                    provenance_meta={"source": "claude_project_prompt"},
                )
            )

        # 2. Project docs
        docs = data.get("docs") or data.get("files") or []
        if isinstance(docs, list):
            for idx, doc in enumerate(docs):
                if not isinstance(doc, dict):
                    continue
                file_name = str(doc.get("file_name") or doc.get("name", f"doc_{idx}")).strip()
                content = str(doc.get("content") or doc.get("text", "")).strip()
                if not content:
                    continue
                payloads.append(
                    NormalizedMemoryPayload(
                        source_kind=CompetitorSourceKind.CLAUDE_PROJECT,
                        source_id=f"{source_id}_{file_name}",
                        raw_content=content,
                        normalized_content=content,
                        layer_recommendation="semantic",
                        tags=["claude_project_doc", file_name],
                        content_hash=_compute_hash(content),
                        provenance_meta={"doc_name": file_name},
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
