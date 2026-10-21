"""Situation Report — pluggable context aggregator for heartbeat ticks.

Provides the framework-level building blocks that let the application
layer assemble a rich "situation report" before each heartbeat execution.
The report is a text summary of recent state changes across registered
data sources (memory, reminders, channels, system health, etc.), injected
into the agent prompt so periodic self-checks become intelligence-driven
rather than blind.

**Harness responsibility** (this file):
    Define the section protocol, context dataclass, and builder.

**Server responsibility** (outside this package):
    Register concrete ``SituationSection`` implementations and call
    ``SituationReportBuilder.build()`` inside ``AgentJobRunner.run()``.

Usage::

    from myrm_agent_harness.toolkits.cron.situation import (
        SituationContext,
        SituationReportBuilder,
        SituationSection,
    )

    class MemoryChangesSection:
        name = "Memory Changes"
        priority = 10

        async def build(self, ctx: SituationContext) -> str | None:
            ...  # query memory store for changes since ctx.last_tick_at

    builder = SituationReportBuilder(token_budget=800)
    builder.register(MemoryChangesSection())
    report = await builder.build(ctx)

[INPUT]
- (none)

[OUTPUT]
- SituationSection: Protocol for a single report section provider.
- SituationContext: Immutable context passed to every section builder.
- SituationReportBuilder: Assembles sections into a budget-constrained report.

[POS]
Situation Report — pluggable context aggregator for heartbeat ticks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_BUDGET = 800
_CHARS_PER_TOKEN = 4.0


@runtime_checkable
class SituationSection(Protocol):
    """A single section provider for the situation report.

    Implementations live in the Server layer; only the protocol is
    defined here so the Harness stays business-agnostic.

    Attributes:
        name:     Human-readable heading rendered as ``## {name}``.
        priority: Lower number = higher priority.  Sections are built
                  concurrently but appended in priority order.
    """

    name: str
    priority: int

    async def build(self, ctx: SituationContext) -> str | None:
        """Return the section body text, or ``None`` to omit silently."""
        ...


@dataclass(frozen=True, slots=True)
class SituationContext:
    """Immutable snapshot passed to every section builder.

    Carries the minimal cross-cutting data that all sections need.
    Section-specific data (e.g. DB handles) should be injected at
    construction time of the concrete section, not added here.
    """

    last_tick_at: datetime | None
    agent_id: str
    user_id: str
    memory_enabled: bool = True


class SituationReportBuilder:
    """Assembles registered sections into a token-budget-constrained report.

    Sections are built **concurrently** (asyncio.gather) for speed, then
    assembled in priority order.  A single failing section is logged and
    skipped — it never aborts the whole report.
    """

    __slots__ = ("_budget_chars", "_sections")

    def __init__(
        self,
        *,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        chars_per_token: float = _CHARS_PER_TOKEN,
    ) -> None:
        if token_budget < 100:
            raise ValueError("token_budget must be >= 100")
        self._sections: list[SituationSection] = []
        self._budget_chars = int(token_budget * chars_per_token)

    def register(self, section: SituationSection) -> None:
        """Add a section provider.  May be called multiple times."""
        self._sections.append(section)

    @property
    def section_count(self) -> int:
        return len(self._sections)

    async def build(self, ctx: SituationContext) -> str:
        """Build the full situation report.

        Returns an empty string when no sections produce content,
        so callers can cheaply skip injection with ``if report:``.
        """
        if not self._sections:
            return ""

        ordered = sorted(self._sections, key=lambda s: s.priority)
        results = await asyncio.gather(
            *(s.build(ctx) for s in ordered),
            return_exceptions=True,
        )

        parts: list[str] = []
        remaining = self._budget_chars

        for section, result in zip(ordered, results, strict=False):
            if isinstance(result, BaseException):
                logger.warning(
                    "Situation section '%s' failed: %s",
                    section.name,
                    result,
                )
                continue
            if result is None:
                continue

            heading = f"## {section.name}\n"
            body = result.rstrip("\n")
            chunk = f"{heading}{body}\n"

            if len(chunk) > remaining:
                usable = remaining - len(heading) - len("\n[... truncated]\n")
                if usable > 40:
                    truncated_body = body[:usable]
                    boundary = _floor_char_boundary(truncated_body)
                    parts.append(f"{heading}{truncated_body[:boundary]}\n[... truncated]\n")
                break

            parts.append(chunk)
            remaining -= len(chunk)

        return "\n".join(parts)


def _floor_char_boundary(text: str) -> int:
    """Find the last valid UTF-8 char boundary at or before len(text).

    Python strings are always valid Unicode, so this just ensures we
    don't split in the middle of a surrogate pair or grapheme cluster
    by backing up to the last newline or space for cleaner truncation.
    """
    for i in range(len(text) - 1, max(len(text) - 50, 0), -1):
        if text[i] in (" ", "\n"):
            return i + 1
    return len(text)
