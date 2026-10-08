# [INPUT]: LivingScratchpadConfig, ScratchpadConduitInjection, ScratchpadDocument
# [OUTPUT]: ScratchpadContextConduit
# [POS]: agent/context_management/living_scratchpad/scratchpad_context_conduit.py

"""Scratchpad context conduit serializing living working memory into structured prompt tags.

[INPUT]
- LivingScratchpadConfig, ScratchpadConduitInjection, ScratchpadDocument: Domain models.

[OUTPUT]
- ScratchpadContextConduit: Formats working memory blocks and extracts pending checklists as prompts.

[POS]
Context injection and prompt projection layer for living scratchpad working memory.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .scratchpad_types import (
    LivingScratchpadConfig,
    ScratchpadConduitInjection,
    ScratchpadDocument,
)


class ScratchpadContextConduit:
    """Serializes scratchpad documents into structured prompt blocks and extracts action cards."""

    def __init__(self, config: LivingScratchpadConfig | None = None) -> None:
        self._config = config or LivingScratchpadConfig()

    def serialize_injection(self, doc: ScratchpadDocument) -> ScratchpadConduitInjection:
        """Constructs an ultra-dense XML block exposing working memory to the model."""
        if not doc.content.strip():
            return ScratchpadConduitInjection(
                tag_text="",
                version=doc.version,
                estimated_tokens=0,
                has_pending_todos=False,
                total_todos=0,
                completed_todos=0,
            )

        total_todos = len(doc.todos)
        completed_todos = doc.completed_todos_count
        pending_todos = doc.pending_todos_count

        todo_meta = f" todos=\"{completed_todos}/{total_todos} completed\"" if total_todos > 0 else ""

        tag_lines = [
            f"<living_scratchpad scope=\"{doc.scope.value}\" version=\"{doc.version}\"{todo_meta}>",
            doc.content.strip(),
            "</living_scratchpad>",
        ]
        tag_text = "\n".join(tag_lines)
        tokens_est = max(1, math.ceil(len(tag_text) / self._config.token_char_ratio))

        return ScratchpadConduitInjection(
            tag_text=tag_text,
            version=doc.version,
            estimated_tokens=tokens_est,
            has_pending_todos=pending_todos > 0,
            total_todos=total_todos,
            completed_todos=completed_todos,
        )

    def extract_pending_todos_prompt(self, doc: ScratchpadDocument) -> str:
        """Extracts all unchecked markdown todos into a standard actionable prompt for the agent."""
        pending = [t for t in doc.todos if not t.is_completed]
        if not pending:
            return ""

        prompt_lines = [
            f"Please proceed with the following pending checklist items from the scratchpad '{doc.title}':",
        ]
        for idx, item in enumerate(pending, start=1):
            prompt_lines.append(f"{idx}. {item.text}")

        return "\n".join(prompt_lines)

    def inject_into_system_prompt(
        self,
        base_system_prompt: str,
        doc: ScratchpadDocument,
    ) -> str:
        """Appends the living scratchpad block cleanly to the system prompt."""
        injection = self.serialize_injection(doc)
        if not injection.tag_text:
            return base_system_prompt

        sep = "\n\n" if base_system_prompt.strip() else ""
        return f"{base_system_prompt}{sep}{injection.tag_text}"
