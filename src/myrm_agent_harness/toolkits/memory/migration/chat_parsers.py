"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/chat_parsers.py
[INPUT]: ChatGPT conversation exports and Claude Project knowledge archives.
[OUTPUT]: ChatExportParser and ClaudeProjectParser producing ExtractedMemoryUnit facts.
"""

from __future__ import annotations

import hashlib
import json

from myrm_agent_harness.toolkits.memory.migration.models import (
    ExtractedMemoryUnit,
    MigrationSourceType,
)
from myrm_agent_harness.toolkits.memory.migration.security_guard import (
    MigrationSecurityGuard,
)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]


class ChatExportParser:
    """Parses ChatGPT and conversation export JSON dumps."""

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
            title = str(conv.get("title", f"Chat_{conv_idx + 1}")).strip()

            # 1. Custom instructions if present
            instructions = conv.get("custom_instructions") or conv.get("instructions")
            if isinstance(instructions, str) and instructions.strip():
                content = instructions.strip()
                cleansed = guard.sanitize_text(content)
                units.append(
                    ExtractedMemoryUnit(
                        source_type=MigrationSourceType.CHATGPT_EXPORT,
                        source_id=f"{source_id}_inst_{conv_idx}",
                        raw_snippet=content,
                        normalized_text=cleansed,
                        layer="profile",
                        tags=["chatgpt_instructions", "user_profile"],
                        content_hash=_hash_content(cleansed),
                        provenance={"source": "chatgpt_instructions", "conversation": title},
                    )
                )

            # 2. Node mapping format
            mapping = conv.get("mapping")
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
                    content_obj = msg.get("content", {})
                    parts = content_obj.get("parts", []) if isinstance(content_obj, dict) else []
                    for part_idx, part in enumerate(parts):
                        if isinstance(part, str) and len(part.strip()) >= 10:
                            if part.strip().lower() in ("ok", "yes", "thanks", "好的", "收到"):
                                continue
                            cleansed = guard.sanitize_text(part)
                            layer = (
                                "profile"
                                if role == "user"
                                and any(k in cleansed for k in ("我喜欢", "偏好", "记住", "习惯"))
                                else "episodic"
                            )
                            units.append(
                                ExtractedMemoryUnit(
                                    source_type=MigrationSourceType.CHATGPT_EXPORT,
                                    source_id=f"{title}_{node_id}_{part_idx}",
                                    raw_snippet=part[:200],
                                    normalized_text=cleansed,
                                    layer=layer,
                                    tags=["chat_export", role],
                                    content_hash=_hash_content(cleansed),
                                    provenance={"title": title, "role": role},
                                )
                            )

            # 3. Linear messages list format
            messages = conv.get("messages")
            if isinstance(messages, list):
                for m_idx, m in enumerate(messages):
                    if not isinstance(m, dict):
                        continue
                    role = str(m.get("role", "unknown"))
                    text = str(m.get("content", "")).strip()
                    if len(text) >= 10:
                        if text.lower() in ("ok", "yes", "thanks", "好的", "收到"):
                            continue
                        cleansed = guard.sanitize_text(text)
                        layer = (
                            "profile"
                            if role == "user"
                            and any(k in cleansed for k in ("我喜欢", "偏好", "记住", "习惯"))
                            else "episodic"
                        )
                        units.append(
                            ExtractedMemoryUnit(
                                source_type=MigrationSourceType.CHATGPT_EXPORT,
                                source_id=f"{title}_m{m_idx}",
                                raw_snippet=text[:200],
                                normalized_text=cleansed,
                                layer=layer,
                                tags=["chat_export", role],
                                content_hash=_hash_content(cleansed),
                                provenance={"title": title, "role": role},
                            )
                        )
        return units


class ClaudeProjectParser:
    """Parses Claude Project export format containing custom instructions and knowledge docs."""

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

        if not isinstance(data, dict):
            return units

        # 1. Project instructions
        prompt = str(data.get("prompt_template") or data.get("custom_instructions") or "").strip()
        if prompt:
            cleansed_prompt = guard.sanitize_text(prompt)
            units.append(
                ExtractedMemoryUnit(
                    source_type=MigrationSourceType.CLAUDE_PROJECT,
                    source_id=f"{source_id}_prompt",
                    raw_snippet=prompt,
                    normalized_text=cleansed_prompt,
                    layer="procedural",
                    tags=["claude_project", "instructions"],
                    content_hash=_hash_content(cleansed_prompt),
                    provenance={"source": "claude_project_prompt"},
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
                cleansed_content = guard.sanitize_text(content)
                units.append(
                    ExtractedMemoryUnit(
                        source_type=MigrationSourceType.CLAUDE_PROJECT,
                        source_id=f"{source_id}_{file_name}",
                        raw_snippet=content[:200],
                        normalized_text=cleansed_content,
                        layer="semantic",
                        tags=["claude_project_doc", file_name],
                        content_hash=_hash_content(cleansed_content),
                        provenance={"doc_name": file_name},
                    )
                )

        return units
