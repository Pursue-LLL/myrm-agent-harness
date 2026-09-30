"""Unit tests for the skill auto-update checker.

[INPUT]
- myrm_agent_harness.agent.skills.market.autoupdate

[OUTPUT]
- pytest suite covering cooldown caching, per-source version comparison,
  origin-based source preference, and the update delegation.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_autoupdate.py
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import myrm_agent_harness.agent.skills.market.autoupdate as autoupdate_mod
from myrm_agent_harness.agent.skills.market.autoupdate import (
    CHECK_COOLDOWN_SECONDS,
    SkillAutoUpdateChecker,
    SkillUpdateInfo,
    UpdateCheckResult,
    get_update_checker,
)
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


class _Source:
    def __init__(self, name: str, detail: SkillSearchResult | None = None, fail: bool = False) -> None:
        self.source_name = name
        self._detail = detail
        self._fail = fail
        self.calls: list[str] = []

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        self.calls.append(skill_id)
        if self._fail:
            raise RuntimeError("source offline")
        return self._detail


def _detail(skill_id: str, version: str) -> SkillSearchResult:
    return SkillSearchResult(
        id=skill_id,
        name=skill_id,
        description="d",
        source="src",
        author="a",
        install_url="https://example.invalid",
        install_method="git",
        version=version,
    )


def _store(*versions: str) -> SimpleNamespace:
    skills = [SimpleNamespace(name=f"skill{i}", version=v) for i, v in enumerate(versions)]
    return SimpleNamespace(list_installed=AsyncMock(return_value=skills))


def _service(*sources: _Source) -> SimpleNamespace:
    return SimpleNamespace(_sources=list(sources))


@pytest.fixture(autouse=True)
def _reset_singleton():
    autoupdate_mod._checker = None
    yield
    autoupdate_mod._checker = None


class TestResultModels:
    def test_has_updates_reflects_any_flag(self) -> None:
        info = SkillUpdateInfo("s", "1.0.0", "2.0.0", "src", "id", True)
        assert UpdateCheckResult(updates=[info]).has_updates is True

    def test_has_updates_false_when_none(self) -> None:
        info = SkillUpdateInfo("s", "1.0.0", "1.0.0", "src", "id", False)
        assert UpdateCheckResult(updates=[info]).has_updates is False

    def test_available_updates_filters(self) -> None:
        yes = SkillUpdateInfo("a", "1.0.0", "2.0.0", "src", "a", True)
        no = SkillUpdateInfo("b", "1.0.0", "1.0.0", "src", "b", False)
        assert UpdateCheckResult(updates=[yes, no]).available_updates == [yes]

    def test_empty_result_defaults(self) -> None:
        result = UpdateCheckResult()
        assert result.updates == []
        assert result.has_updates is False
        assert result.checked_at > 0


class TestMissingDependencies:
    @pytest.mark.asyncio
    async def test_without_skill_store_skips(self) -> None:
        checker = SkillAutoUpdateChecker(market_service=_service())
        assert (await checker.check_updates()).updates == []

    @pytest.mark.asyncio
    async def test_without_market_service_skips(self) -> None:
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"))
        assert (await checker.check_updates()).updates == []

    @pytest.mark.asyncio
    async def test_no_installed_skills(self) -> None:
        store = SimpleNamespace(list_installed=AsyncMock(return_value=[]))
        checker = SkillAutoUpdateChecker(skill_store=store, market_service=_service())
        result = await checker.check_updates()
        assert result.updates == []
        assert checker._last_check is not None


class TestCheckUpdates:
    @pytest.mark.asyncio
    async def test_detects_newer_remote_version(self) -> None:
        source = _Source("github", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        result = await checker.check_updates()

        assert result.has_updates is True
        assert result.updates[0].remote_version == "2.0.0"
        assert result.updates[0].source == "github"

    @pytest.mark.asyncio
    async def test_marks_older_remote_as_no_update(self) -> None:
        source = _Source("github", _detail("pdf", "1.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        result = await checker.check_updates()

        assert result.has_updates is False

    @pytest.mark.asyncio
    async def test_skips_default_and_missing_versions(self) -> None:
        source = _Source("github", _detail("pdf", "2.0.0"))
        store = _store("1.0.0", "")
        checker = SkillAutoUpdateChecker(skill_store=store, market_service=_service(source))

        result = await checker.check_updates()

        assert result.updates == []
        assert source.calls == []

    @pytest.mark.asyncio
    async def test_skips_prebuilt_sources(self) -> None:
        prebuilt = _Source("prebuilt", _detail("pdf", "9.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(prebuilt))

        assert (await checker.check_updates()).updates == []

    @pytest.mark.asyncio
    async def test_falls_back_to_next_source_on_failure(self) -> None:
        broken = _Source("broken", fail=True)
        healthy = _Source("github", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(broken, healthy))

        result = await checker.check_updates()

        assert [u.source for u in result.updates] == ["github"]
        assert broken.calls == ["skill0"]

    @pytest.mark.asyncio
    async def test_ignores_missing_remote_version(self) -> None:
        source = _Source("github", _detail("pdf", ""))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        assert (await checker.check_updates()).updates == []

    @pytest.mark.asyncio
    async def test_ignores_missing_detail(self) -> None:
        source = _Source("github", None)
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        assert (await checker.check_updates()).updates == []

    @pytest.mark.asyncio
    async def test_prefers_origin_source_when_recorded(self, tmp_path, monkeypatch) -> None:
        import myrm_agent_harness.agent.skills.market.helpers as helpers_mod

        monkeypatch.setattr(helpers_mod, "read_origin", lambda _path: {"source": "lobehub"})
        lobehub = _Source("lobehub", _detail("pdf", "2.0.0"))
        github = _Source("github", _detail("pdf", "3.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(github, lobehub))

        result = await checker.check_updates()

        assert [u.source for u in result.updates] == ["lobehub"]
        assert github.calls == []

    @pytest.mark.asyncio
    async def test_ignores_unrecorded_origin_source(self, monkeypatch) -> None:
        import myrm_agent_harness.agent.skills.market.helpers as helpers_mod

        monkeypatch.setattr(helpers_mod, "read_origin", lambda _path: {"source": "unknown"})
        github = _Source("github", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(github))

        assert [u.source for u in (await checker.check_updates()).updates] == ["github"]

    @pytest.mark.asyncio
    async def test_stops_after_first_update(self) -> None:
        first = _Source("github", _detail("pdf", "3.0.0"))
        second = _Source("lobehub", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(first, second))

        await checker.check_updates()

        assert second.calls == []


class TestCooldown:
    @pytest.mark.asyncio
    async def test_second_call_within_cooldown_is_cached(self) -> None:
        source = _Source("github", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        first = await checker.check_updates()
        second = await checker.check_updates()

        assert second is first
        assert len(source.calls) == 1

    @pytest.mark.asyncio
    async def test_force_bypasses_cooldown(self) -> None:
        source = _Source("github", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        await checker.check_updates()
        await checker.check_updates(force=True)

        assert len(source.calls) == 2

    @pytest.mark.asyncio
    async def test_expired_cooldown_rechecks(self) -> None:
        source = _Source("github", _detail("pdf", "2.0.0"))
        checker = SkillAutoUpdateChecker(skill_store=_store("1.0.1"), market_service=_service(source))

        await checker.check_updates()
        checker._last_check.checked_at -= CHECK_COOLDOWN_SECONDS + 1
        await checker.check_updates()

        assert len(source.calls) == 2


class TestUpdateSkill:
    @pytest.mark.asyncio
    async def test_delegates_to_market_service(self) -> None:
        market = SimpleNamespace(install=AsyncMock(return_value="installed"))
        checker = SkillAutoUpdateChecker(market_service=market)
        info = SkillUpdateInfo("pdf", "1.0.0", "2.0.0", "github", "acme/pdf", True)

        assert await checker.update_skill(info) == "installed"
        assert market.install.await_args.kwargs == {"skill_id": "acme/pdf", "source": "github"}

    @pytest.mark.asyncio
    async def test_without_market_service_fails(self) -> None:
        checker = SkillAutoUpdateChecker()
        info = SkillUpdateInfo("pdf", "1.0.0", "2.0.0", "github", "acme/pdf", True)

        result = await checker.update_skill(info)

        assert result.success is False
        assert "No SkillMarketService" in (result.error or "")


class TestSingleton:
    @pytest.mark.asyncio
    async def test_singleton_is_created_once(self) -> None:
        store = _store("1.0.1")
        source = _Source("github", _detail("pdf", "2.0.0"))
        first = get_update_checker(store, _service(source))
        second = get_update_checker()

        assert first is second
        assert (await second.check_updates()).has_updates is True

    def test_singleton_without_dependencies_is_usable(self) -> None:
        assert get_update_checker() is get_update_checker()
