"""Compaction Directives Injector compiling user directives into summarizer prompts.

Parses preservation directives from markdown or configs (such as CLAUDE.md)
and injects structured preservation requirements into the summarizer prompt template.

[INPUT]
- agent.context_management.custom_compaction_directives.compaction_directives_types::PreservationDirective,
  PreservationDirectiveKind (POS: Data contracts and type definitions for custom compaction directives and
  preservation whitelist.)

[OUTPUT]
- CompactionDirectivesInjector: Compiles and injects custom domain preservation instructions into compaction
  prompts.

[POS]
Compaction Directives Injector compiling user directives into summarizer prompts.
"""

from __future__ import annotations

import re
from typing import Sequence

from .compaction_directives_types import (
    PreservationDirective,
    PreservationDirectiveKind,
)


class CompactionDirectivesInjector:
    """Compiles and injects custom domain preservation instructions into compaction prompts."""

    DIRECTIVES_HEADER = "\n\n## DOMAIN PRESERVATION DIRECTIVES (USER DEFINED - HIGHEST PRIORITY)"

    def parse_from_markdown_block(self, text: str) -> list[PreservationDirective]:
        """Parse structured preservation directives from a 'Compact instructions' markdown block."""
        directives: list[PreservationDirective] = []
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        for idx, line in enumerate(lines, 1):
            if not line.startswith(("-", "*")):
                continue
            content = line.lstrip("-* ").strip()
            if not content:
                continue

            # Heuristically classify directive kind
            lower = content.lower()
            if "verbatim" in lower or "exact" in lower:
                kind = PreservationDirectiveKind.MUST_PRESERVE_VERBATIM
            elif "identifier" in lower or "path" in lower or "port" in lower or "token" in lower:
                kind = PreservationDirectiveKind.PRESERVE_IDENTIFIER
            elif "decision" in lower or "architecture" in lower:
                kind = PreservationDirectiveKind.PRESERVE_DECISION
            elif "todo" in lower or "pending" in lower:
                kind = PreservationDirectiveKind.PRESERVE_TODO
            else:
                kind = PreservationDirectiveKind.CUSTOM_RULE

            # Extract quoted words as required entities
            quoted_entities = re.findall(r"['\"]([^'\"]+)['\"]", content)
            # Extract identifiers (e.g. paths or env vars)
            raw_keywords = [w for w in re.split(r"[\s,;]+", content) if len(w) > 3 and not w.startswith(("the", "and", "for"))]

            directives.append(
                PreservationDirective(
                    directive_id=f"dir-{idx:03d}",
                    kind=kind,
                    instruction=content,
                    required_keywords=raw_keywords[:5],
                    required_entities=quoted_entities,
                    priority=idx * 10,
                )
            )

        return directives

    def format_directives_prompt_slot(self, directives: Sequence[PreservationDirective]) -> str:
        """Format an array of directives into an authoritative prompt block for LLM summarizers."""
        if not directives:
            return ""

        sorted_directives = sorted(directives, key=lambda d: d.priority)
        lines: list[str] = [
            self.DIRECTIVES_HEADER,
            "The user has defined strict domain preservation instructions. You MUST strictly preserve all facts listed below verbatim:",
        ]

        for d in sorted_directives:
            entities_str = f" [Required: {', '.join(d.required_entities)}]" if d.required_entities else ""
            lines.append(f"- [{d.kind.value.upper()}] {d.instruction}{entities_str}")

        lines.append(
            "Do NOT omit, simplify, or abstract away these facts under any compression constraint.\n"
        )
        return "\n".join(lines)

    def inject_into_prompt(
        self,
        base_prompt: str,
        directives: Sequence[PreservationDirective],
    ) -> str:
        """Inject compiled directives block into base summarization prompt template."""
        if not directives:
            return base_prompt

        slot_text = self.format_directives_prompt_slot(directives)
        # Check if placeholder exists
        if "{custom_directives}" in base_prompt:
            return base_prompt.replace("{custom_directives}", slot_text)

        # Insert before Conversation History or append at the end
        if "## Conversation History" in base_prompt:
            return base_prompt.replace(
                "## Conversation History",
                f"{slot_text}\n## Conversation History",
                1,
            )
        if "## Merge Rules" in base_prompt:
            return base_prompt.replace(
                "## Merge Rules",
                f"{slot_text}\n## Merge Rules",
                1,
            )

        return f"{base_prompt.rstrip()}\n{slot_text}"
