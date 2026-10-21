"""Unit tests for skill market service source registry and cache helpers.

[INPUT]
- myrm_agent_harness.agent.skills.market.service::BaseSkillMarketService
- myrm_agent_harness.backends.skills.market_protocols::SkillSearchResult

[OUTPUT]
- pytest suite covering source registration, the search-result cache, and
  per-source failure isolation.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_service_registry.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


def _result(skill_id: str, source: str, *, name: str = "", version: str = "") -> SkillSearchResult:
    return SkillSearchResult(
        id=skill_id,
        name=name or skill_id,
        description="d",
        source=source,
        author="a",
        install_url="https://example.invalid",
        install_method="git",
        version=version,
    )


class _StubSource:
    """Minimal SkillSource stand-in that records how often it was queried."""

    def __init__(self, name: str, *, detail: SkillSearchResult | None = None, fail: bool = False) -> None:
        self.source_name = name
        self._detail = detail
        self._fail = fail
        self.search_calls = 0

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        self.search_calls += 1
        if self._fail:
            raise RuntimeError("source offline")
        return [_result(f"{self.source_name}:{query}", self.source_name)]

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        return self._detail


@pytest.fixture
def service() -> BaseSkillMarketService:
    return BaseSkillMarketService()


def test_default_sources_are_registered(service: BaseSkillMarketService) -> None:
    names = {s.source_name for s in service._sources}
    assert {
        "static_index",
        "github",
        "clawhub",
        "skills_sh",
        "lobehub",
        "modelscope",
        "aliyun",
    } == names


def test_register_source_appends_and_is_idempotent(service: BaseSkillMarketService) -> None:
    source = _StubSource("custom")
    service.register_source(source)
    service.register_source(_StubSource("custom"))

    matches = [s for s in service._sources if s.source_name == "custom"]
    assert len(matches) == 1
    assert matches[0] is source


def test_unregister_source_reports_removal(service: BaseSkillMarketService) -> None:
    service.register_source(_StubSource("custom"))
    assert service.unregister_source("custom") is True
    assert service.unregister_source("custom") is False


@pytest.mark.asyncio
async def test_get_detail_falls_back_to_source(service: BaseSkillMarketService) -> None:
    detail = _result("custom:skill", "custom")
    service.register_source(_StubSource("custom", detail=detail))

    assert await service.get_detail("custom:skill", "custom") is detail
    assert await service.get_detail("missing", "nowhere") is None


@pytest.mark.asyncio
async def test_get_detail_serves_from_search_cache(service: BaseSkillMarketService) -> None:
    cached = _result("custom:q", "custom")
    source = _StubSource("custom")
    service.register_source(source)
    service._search_cache["q"] = (0.0, [cached])

    assert await service.get_detail("custom:q", "custom") is cached
    assert source.search_calls == 0


@pytest.mark.asyncio
async def test_search_source_isolates_source_failure(service: BaseSkillMarketService) -> None:
    broken = _StubSource("broken", fail=True)
    healthy = _StubSource("healthy")

    assert await service._search_source(broken, "q", 5) == []
    assert len(await service._search_source(healthy, "q", 5)) == 1


def test_enrich_results_marks_upgrades_against_local_version(service: BaseSkillMarketService) -> None:
    older = _result("s:1", "custom", name="Alpha", version="1.0.0")
    newer = _result("s:2", "custom", name="Beta", version="2.0.0")

    enriched = service._enrich_results([older, newer], {"alpha": "1.0.0", "beta": "0.9.0"})

    assert enriched[0].installed_version == "1.0.0"
    assert enriched[0].upgrade_available is False
    assert enriched[1].installed_version == "0.9.0"
    assert enriched[1].upgrade_available is True


def test_enrich_results_without_local_versions_returns_passthrough(
    service: BaseSkillMarketService,
) -> None:
    results = [_result("s:1", "custom", name="Alpha", version="1.0.0")]

    enriched = service._enrich_results(results, None)

    assert [e.result for e in enriched] == results
    assert enriched[0].installed_version == ""
