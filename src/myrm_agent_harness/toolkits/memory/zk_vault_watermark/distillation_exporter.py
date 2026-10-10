"""Sensitivity tiering and safe knowledge distillation exporter (Item 159).

[INPUT]
- DistilledMemoryItem records, target sensitivity tier, and PII redaction toggles.

[OUTPUT]
- Distilled, sanitized memory entries and structured Markdown export documents.

[POS]
- Distillation exporter in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

import re

from .models import DistilledMemoryItem, MemorySensitivityTier

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_IP_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_TOKEN_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{8,})['\"]?")


class SensitivityDistillationExporter:
    """Classifies memory sensitivity tiers and distills sanitized knowledge assets for external sharing."""

    @staticmethod
    def _redact_sensitive_tokens(content: str) -> str:
        """Sanitize PII entities, ip addresses, and secret tokens using deterministic masks."""
        sanitized = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", content)
        sanitized = _IP_PATTERN.sub("[REDACTED_IP]", sanitized)
        sanitized = _TOKEN_PATTERN.sub(r"\1: [REDACTED_SECRET]", sanitized)
        return sanitized

    def distill_memories(
        self,
        items: list[DistilledMemoryItem],
        target_tier: MemorySensitivityTier = "public_sharable",
        redact_pii: bool = True,
    ) -> list[DistilledMemoryItem]:
        """Filter and distill memories according to target sharing boundary."""
        distilled: list[DistilledMemoryItem] = []

        for item in items:
            # 1. Strictly private items are completely withheld from public and team exports
            if item.sensitivity_tier == "strictly_private_pii":
                if target_tier == "strictly_private_pii":
                    distilled.append(item)
                continue

            # 2. Team internal items are excluded from public sharable exports
            if item.sensitivity_tier == "team_internal":
                if target_tier == "public_sharable":
                    continue
                # If exported for team, perform light redaction if requested
                content = (
                    self._redact_sensitive_tokens(item.content)
                    if redact_pii
                    else item.content
                )
                distilled.append(
                    DistilledMemoryItem(
                        memory_id=item.memory_id,
                        content=content,
                        sensitivity_tier=item.sensitivity_tier,
                        category=item.category,
                        redacted=redact_pii and content != item.content,
                    )
                )
                continue

            # 3. Public sharable items are preserved
            content = (
                self._redact_sensitive_tokens(item.content)
                if redact_pii
                else item.content
            )
            distilled.append(
                DistilledMemoryItem(
                    memory_id=item.memory_id,
                    content=content,
                    sensitivity_tier=item.sensitivity_tier,
                    category=item.category,
                    redacted=redact_pii and content != item.content,
                )
            )

        return distilled

    @staticmethod
    def render_markdown_document(
        items: list[DistilledMemoryItem],
        target_tier: MemorySensitivityTier,
    ) -> str:
        """Format distilled memories into a coherent Markdown export package."""
        lines: list[str] = [
            f"# Myrm Autonomous Memory Export ({target_tier.upper()})",
            "",
            "> Exported knowledge assets governed by sensitivity tiering and provenance watermarking.",
            "",
        ]

        for item in items:
            redacted_tag = " [REDACTED]" if item.redacted else ""
            lines.extend(
                [
                    f"### [{item.category.upper()}] {item.memory_id}{redacted_tag}",
                    f"- **Tier**: `{item.sensitivity_tier}`",
                    f"- **Content**: {item.content.strip()}",
                    "",
                ]
            )

        return "\n".join(lines)
