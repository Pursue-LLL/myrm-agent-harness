"""Prompt Budget Guard.

Enforces absolute token/character budgets on dynamic prompt injection
(like memory context) to preserve LLM Prompt Cache prefix stability
and prevent context window overflow.

[INPUT]
- (none)

[OUTPUT]
- PromptBudgetGuardConfig: Enforces absolute budget limits on prompt sections.
- BudgetedSection: class — Budgeted Section
- PromptBudgetGuard: class — Prompt Budget Guard

[POS]
Prompt Budget Guard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TypedDict

logger = logging.getLogger(__name__)

# Approximate characters per token (conservative)
CHARS_PER_TOKEN = 4


class PromptBudgetGuardConfig(TypedDict, total=False):
    max_tokens: int
    truncation_message: str


@dataclass
class BudgetedSection:
    title: str
    items: list[str]
    priority: int  # Lower number = higher priority to keep


class PromptBudgetGuard:
    """Enforces absolute budget limits on prompt sections."""

    def __init__(
        self,
        max_tokens: int = 2500,
        truncation_message: str = "\n... (Some lower-priority items were truncated. Use memory_recall to search for more.)",
    ) -> None:
        self.max_chars = max_tokens * CHARS_PER_TOKEN
        self.truncation_message = truncation_message

    def apply_budget(self, sections: list[BudgetedSection], base_text: str = "") -> str:
        """Apply budget to a list of sections and return the formatted string.

        Sections are prioritized. Items within sections are kept until budget is exhausted.
        """
        # Sort sections by priority (0 is highest)
        sorted_sections = sorted(sections, key=lambda s: s.priority)

        current_length = len(base_text)
        formatted_parts: list[str] = []
        truncated = False

        for section in sorted_sections:
            if not section.items:
                continue

            section_header = f"## {section.title}\n"
            if current_length + len(section_header) > self.max_chars:
                truncated = True
                break

            current_length += len(section_header)
            accepted_items: list[str] = []

            for item in section.items:
                item_str = f"- {item}\n"
                if current_length + len(item_str) > self.max_chars:
                    truncated = True
                    break
                accepted_items.append(item)
                current_length += len(item_str)

            if accepted_items:
                formatted_parts.append(section_header + "".join(f"- {i}\n" for i in accepted_items).strip())

            if truncated:
                break

        final_text = base_text + "\n\n".join(formatted_parts)
        if truncated and self.truncation_message:
            final_text += self.truncation_message

        return final_text.strip()
