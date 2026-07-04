"""Tests for CrawlEngine L4 escalation hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine
from myrm_agent_harness.toolkits.web_fetch.escalation.protocols import EscalationFetchResult
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType


class _StubProvider:
    provider_id = "stub"

    def __init__(self, result: EscalationFetchResult | None) -> None:
        self._result = result
        self.fetch_url = AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_try_escalation_returns_document_when_provider_succeeds() -> None:
    engine = CrawlEngine()
    provider = _StubProvider(
        EscalationFetchResult(
            url="https://example.com",
            content="# Title\n\nBody text",
            title="Title",
            provider_id="stub",
        )
    )
    engine.set_escalation_providers([provider])

    doc, fetch_result = await engine._try_escalation("https://example.com")

    assert doc is not None
    assert "Body text" in doc.page_content
    assert doc.metadata.get("escalation_provider") == "stub"
    assert fetch_result is None
    provider.fetch_url.assert_awaited_once()


@pytest.mark.asyncio
async def test_crawl_with_degradation_skips_escalation_when_disabled() -> None:
    engine = CrawlEngine()
    provider = _StubProvider(
        EscalationFetchResult(url="https://example.com", content="remote", provider_id="stub")
    )
    engine.set_escalation_providers([provider])

    with patch.object(engine, "_try_and_report", new=AsyncMock(return_value=(None, True, 0.0, None, None, None))):
        doc, _ = await engine._crawl_with_degradation("https://example.com", allow_escalation=False)

    assert doc is None
    provider.fetch_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_escalation_prefers_context_over_instance_providers() -> None:
    from myrm_agent_harness.toolkits.web_fetch.escalation.context import bind_web_fetch_escalation_context

    instance_provider = _StubProvider(
        EscalationFetchResult(url="https://example.com", content="instance", provider_id="instance")
    )
    context_provider = _StubProvider(
        EscalationFetchResult(url="https://example.com", content="context", provider_id="context")
    )
    engine = CrawlEngine()
    engine.set_escalation_providers([instance_provider])

    with bind_web_fetch_escalation_context(providers=[context_provider], launch_mode=None):
        doc, _ = await engine._try_escalation("https://example.com")

    assert doc is not None
    assert doc.page_content == "context"
    context_provider.fetch_url.assert_awaited_once()
    instance_provider.fetch_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_escalation_records_failure_when_all_providers_fail() -> None:
    from myrm_agent_harness.toolkits.web_fetch.escalation.metrics import web_fetch_escalation_metrics

    before = web_fetch_escalation_metrics.snapshot()["failure_count"]
    engine = CrawlEngine()
    provider = _StubProvider(None)
    engine.set_escalation_providers([provider])

    doc, _ = await engine._try_escalation("https://example.com")

    assert doc is None
    assert web_fetch_escalation_metrics.snapshot()["failure_count"] == before + 1


@pytest.mark.asyncio
async def test_crawl_with_degradation_calls_escalation_after_l3_failure() -> None:
    engine = CrawlEngine()
    provider = _StubProvider(
        EscalationFetchResult(url="https://example.com", content="remote body", provider_id="stub")
    )
    engine.set_escalation_providers([provider])

    with patch.object(engine, "_try_and_report", new=AsyncMock(return_value=(None, True, 0.0, None, None, None))):
        with patch.object(engine._router, "select") as mock_select:
            from myrm_agent_harness.toolkits.web_fetch.router.models import FetcherDecision

            mock_select.return_value = FetcherDecision(fetcher_type=FetcherType.HTTP, reason="test")
            doc, _ = await engine._crawl_with_degradation("https://example.com", allow_escalation=True)

    assert doc is not None
    assert doc.page_content == "remote body"
    provider.fetch_url.assert_awaited_once()
