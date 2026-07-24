"""FetchEngine L4 escalation and platform fast-path helpers.

[POS]
Mixin: remote fetch escalation after local L1-L3 exhaustion; bilibili cookie loader.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from .fetchers.protocols import FetcherType, FetchResult

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine

logger = logging.getLogger(__name__)


class FetchEngineEscalationMixin:
    async def _load_bilibili_cookies(self: FetchEngine) -> dict[str, str] | None:
        """Load bilibili.com cookies from SessionVault for subtitle API access."""
        vault = self._http_fetcher._session_vault
        if not vault:
            return None
        try:
            entry = await vault.load("bilibili.com")
            if not entry or not entry.storage_state or "cookies" not in entry.storage_state:
                return None
            return {c["name"]: c["value"] for c in entry.storage_state["cookies"] if "name" in c and "value" in c}
        except Exception:
            return None

    async def _try_escalation(
        self: FetchEngine, url: str, *, max_chars: int = 0
    ) -> tuple[Document | None, FetchResult | None]:
        """Try injected remote providers after local L1-L3 exhaustion."""
        from .escalation.context import get_bound_escalation_providers

        providers = get_bound_escalation_providers() or self._escalation_providers
        if not providers:
            return None, None

        from .escalation.metrics import web_fetch_escalation_metrics

        web_fetch_escalation_metrics.record_triggered()
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                "agent_status",
                {
                    "event": "tool_fallback",
                    "tool": "web_fetch_tool",
                    "fallback_type": "remote_fetch",
                    "message": "Local fetch exhausted, trying remote reader fallback...",
                },
            )
        except Exception:
            pass

        for provider in providers:
            try:
                escalation_result = await provider.fetch_url(url, max_chars=max_chars)
            except Exception as exc:
                logger.warning("Escalation provider %s failed for %s: %s", provider.provider_id, url, exc)
                continue

            if escalation_result is None or not escalation_result.content.strip():
                continue

            if escalation_result.is_markdown:
                content = escalation_result.content
                if max_chars > 0 and len(content) > max_chars:
                    content = content[:max_chars]
                doc = Document(
                    page_content=content,
                    metadata={
                        "url": escalation_result.url or url,
                        "title": escalation_result.title,
                        "escalation_provider": provider.provider_id,
                    },
                )
            else:
                remote_fetch = FetchResult(
                    html=escalation_result.content,
                    url=escalation_result.url or url,
                    fetcher_type=FetcherType.HTTP,
                )
                doc = self._pipeline.process(remote_fetch, max_chars=max_chars)
                if doc is None:
                    continue
                doc.metadata["escalation_provider"] = provider.provider_id

            web_fetch_escalation_metrics.record_success()
            logger.info("Escalation provider %s succeeded for %s", provider.provider_id, url)
            return doc, None

        web_fetch_escalation_metrics.record_failure()
        return None, None
