from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.enhancers.dom_enhancer_loader import get_dom_enhancer_script
from myrm_agent_harness.toolkits.browser.session.interactor import RefNotFoundMetrics
from myrm_agent_harness.toolkits.browser.wait_strategies import (
    WaitMetrics,
    WaitStrategy,
    _record_to_domain_metrics,
    wait_for_page_ready,
)


def test_interactor_metrics_properties():
    metrics = RefNotFoundMetrics()
    assert metrics.failure_rate == 0.0
    assert metrics.recent_failure_rate == 0.0

    metrics.record_interaction(True, "ref1", "click")
    assert metrics.failure_rate == 1.0
    assert metrics.recent_failure_rate == 1.0
    assert len(metrics.top_failed_refs) == 1
    assert len(metrics.top_failed_actions) == 1

    metrics.to_dict()

def test_dom_enhancer_loader():
    script = get_dom_enhancer_script()
    assert "window.__myrm_enhancer_initialized" in script

def test_record_wait_metrics_spa_stable():
    metrics = WaitMetrics(strategy=WaitStrategy.SPA_STABLE, reason="quiet", elapsed_ms=100)
    domain_manager = MagicMock()
    domain_metrics = MagicMock()
    domain_manager.get_or_create.return_value = domain_metrics
    _record_to_domain_metrics(metrics, "example.com", domain_manager)
    domain_metrics.record_wait_strategy.assert_called_with("dom_stable", 100)

@pytest.mark.asyncio
async def test_wait_for_page_ready_spa_stable():
    page = AsyncMock()
    # Mock evaluate to return dict for wait_spa_stable
    page.evaluate.return_value = {"stable": True, "inflightRequests": 0}
    metrics = await wait_for_page_ready(page, strategy=WaitStrategy.SPA_STABLE, max_ms=10)
    assert metrics.strategy == WaitStrategy.SPA_STABLE


def test_dom_enhancer_loader_exception(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, "read_text", MagicMock(side_effect=Exception("mocked error")))
    import myrm_agent_harness.toolkits.browser.enhancers.dom_enhancer_loader as loader
    loader.get_dom_enhancer_script.cache_clear()
    script = loader.get_dom_enhancer_script()
    assert script == ""

def test_record_wait_metrics_other_strategies():
    domain_manager = MagicMock()
    domain_metrics = MagicMock()
    domain_manager.get_or_create.return_value = domain_metrics

    metrics1 = WaitMetrics(strategy=WaitStrategy.NETWORKIDLE, reason="network_only", elapsed_ms=100)
    _record_to_domain_metrics(metrics1, "example.com", domain_manager)

    metrics2 = WaitMetrics(strategy=WaitStrategy.HYBRID, reason="both", elapsed_ms=100, network_idle_ms=50, dom_stable_ms=50)
    _record_to_domain_metrics(metrics2, "example.com", domain_manager)

    metrics3 = WaitMetrics(strategy=WaitStrategy.SMART, reason="quiet", elapsed_ms=100, dom_stable_ms=50)
    _record_to_domain_metrics(metrics3, "example.com", domain_manager)

    # Exception path
    domain_manager.get_or_create.side_effect = Exception("mocked error")
    _record_to_domain_metrics(metrics1, "example.com", domain_manager)

