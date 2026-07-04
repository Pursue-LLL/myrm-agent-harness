"""Fetch escalation Protocol and result types (server implements providers)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class EscalationFetchResult:
    """Normalized remote fetch output before ContentPipeline / Document assembly."""

    url: str
    content: str
    title: str = ""
    provider_id: str = ""
    is_markdown: bool = True


@runtime_checkable
class FetchEscalationProvider(Protocol):
    """Optional L4 provider injected from the business layer (Jina, Firecrawl, etc.)."""

    provider_id: str

    async def fetch_url(self, url: str, *, max_chars: int = 0) -> EscalationFetchResult | None:
        """Fetch URL via remote service. Returns None on failure."""
        ...
