"""Tests for the SkillCurator engine — stateless lifecycle sweep logic.

Covers:
- Basic sweep with no transitions needed
- Stale transition for inactive skills
- Archive promotion for long-stale skills
- Pinned skill exemption
- Grace period exemption
- LRU eviction when active count exceeds max_skills
- Low quality detection
- Error resilience (bad skill data)
- Stale auto-recovery on usage (via SkillStatsCollector integration)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.curator import CuratorRunResult, SkillCurator
from myrm_agent_harness.agent.skills.curator.types import CuratorTransition
from myrm_agent_harness.backends.skills.forgetting_strategy import CuratorConfig
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillTrust,
    SkillUsageStats,
)


def _make_skill(
    name: str,
    *,
    call_count: int = 10,
    success_count: int = 8,
    failure_count: int = 2,
    last_used_days_ago: int | None = 5,
    lifecycle_status: str = SkillLifecycleStatus.ACTIVE,
    pinned: bool = False,
    trust: SkillTrust = SkillTrust.TRUSTED,
    storage_path: str | None = None,
    created_days_ago: int = 30,
) -> SkillMetadata:
    """Create a SkillMetadata with configurable usage stats for testing."""
    now = datetime.now(UTC)
    last_used = now - timedelta(days=last_used_days_ago) if last_used_days_ago is not None else None
    created_at = now - timedelta(days=created_days_ago)

    return SkillMetadata(
        name=name,
        description=f"Test skill: {name}",
        trust=trust,
        storage_path=storage_path or f"/tmp/test_skills/{name}",
        usage_stats=SkillUsageStats(
            call_count=call_count,
            success_count=success_count,
            failure_count=failure_count,
            last_used_at=last_used,
            lifecycle_status=lifecycle_status,
            pinned=pinned,
            created_at=created_at,
        ),
    )


@pytest.fixture()
def tmp_skills_dir(tmp_path: Path) -> Path:
    """Provide a temporary skills directory with a dummy skill."""
    skill_dir = tmp_path / "test_skill"
    skill_dir.mkdir()
    return tmp_path


@pytest.fixture()
def collector(tmp_skills_dir: Path) -> SkillStatsCollector:
    return SkillStatsCollector(tmp_skills_dir)


# ── Basic sweep ──────────────────────────────────────────────────────────


class TestBasicSweep:
    def test_empty_skills_list(self, collector: SkillStatsCollector) -> None:
        curator = SkillCurator(collector)
        result = curator.run([], force=True)
        assert result.skills_scanned == 0
        assert result.total_transitions == 0

    def test_no_transitions_for_healthy_skills(self, collector: SkillStatsCollector) -> None:
        skills = [_make_skill("healthy_a"), _make_skill("healthy_b")]
        curator = SkillCurator(collector)
        result = curator.run(skills, force=True)
        assert result.skills_scanned == 2
        assert result.total_transitions == 0

    def test_disabled_curator_skips_without_force(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(enabled=False)
        curator = SkillCurator(collector, config)
        skills = [_make_skill("should_be_stale", last_used_days_ago=100)]
        result = curator.run(skills)
        assert result.skills_scanned == 0
        assert result.total_transitions == 0

    def test_disabled_curator_runs_with_force(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(enabled=False, stale_after_days=7)
        curator = SkillCurator(collector, config)
        skills = [_make_skill("should_be_stale", last_used_days_ago=100)]
        result = curator.run(skills, force=True)
        assert result.skills_scanned == 1


# ── Lifecycle transitions ────────────────────────────────────────────────


class TestLifecycleTransitions:
    def test_stale_transition_for_inactive_skill(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=10)
        skills = [_make_skill("inactive", last_used_days_ago=15)]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        assert result.stale_count >= 1
        stale_names = [t.skill_name for t in result.transitions if t.to_status == "stale"]
        assert "inactive" in stale_names

    def test_archive_promotion_for_long_stale_skill(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=10, archive_after_days=30)
        skills = [
            _make_skill(
                "long_stale",
                last_used_days_ago=60,
                lifecycle_status=SkillLifecycleStatus.STALE,
            )
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        archived_names = [t.skill_name for t in result.transitions if t.to_status == "archived"]
        assert "long_stale" in archived_names

    def test_never_used_skill_becomes_stale(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7)
        skills = [
            _make_skill("never_used", call_count=0, success_count=0, failure_count=0, last_used_days_ago=None)
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        assert result.stale_count >= 1

    def test_low_quality_skill_becomes_stale(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(min_success_rate=0.5, stale_after_days=365)
        skills = [
            _make_skill(
                "low_quality",
                call_count=10,
                success_count=2,
                failure_count=8,
                last_used_days_ago=1,
            )
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        stale_names = [t.skill_name for t in result.transitions if t.to_status == "stale"]
        assert "low_quality" in stale_names


# ── Exemptions ───────────────────────────────────────────────────────────


class TestExemptions:
    def test_pinned_skill_exempt_from_transitions(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7)
        skills = [_make_skill("pinned_inactive", last_used_days_ago=100, pinned=True)]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        assert result.total_transitions == 0
        assert result.skipped_pinned == 1

    def test_grace_period_exempts_new_skills(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7, grace_period_days=14)
        skills = [
            _make_skill(
                "brand_new",
                call_count=0,
                success_count=0,
                failure_count=0,
                last_used_days_ago=None,
                created_days_ago=3,
            )
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        assert result.total_transitions == 0

    def test_installed_skill_optionally_exempt(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7, protect_installed_skills=True)
        skills = [
            _make_skill("hub_skill", last_used_days_ago=100, trust=SkillTrust.INSTALLED)
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        assert result.total_transitions == 0


# ── LRU eviction ─────────────────────────────────────────────────────────


class TestLRUEviction:
    def test_lru_eviction_when_exceeds_max(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(max_skills=3, stale_after_days=365)
        skills = [
            _make_skill(f"skill_{i}", last_used_days_ago=50 - i)
            for i in range(5)
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        lru_transitions = [t for t in result.transitions if t.reason_type == "lru_eviction"]
        assert len(lru_transitions) == 2

    def test_lru_eviction_skips_no_storage_path(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(max_skills=2, stale_after_days=365)
        normal = _make_skill("normal", last_used_days_ago=50)
        no_path = _make_skill("no_path", last_used_days_ago=100, storage_path=None)
        no_path.storage_path = None
        recent = _make_skill("recent", last_used_days_ago=1)
        curator = SkillCurator(collector, config)
        result = curator.run([normal, no_path, recent], force=True)
        error_names = [e for e in result.errors if "no_path" in e]
        assert len(error_names) >= 1

    def test_lru_skips_already_transitioned(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(max_skills=2, stale_after_days=5)
        skills = [
            _make_skill("already_stale_by_inactivity", last_used_days_ago=100),
            _make_skill("recent_a", last_used_days_ago=1),
            _make_skill("recent_b", last_used_days_ago=2),
        ]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        transitioned_names = {t.skill_name for t in result.transitions}
        assert "already_stale_by_inactivity" in transitioned_names

    def test_no_lru_eviction_under_threshold(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(max_skills=10, stale_after_days=365)
        skills = [_make_skill(f"skill_{i}") for i in range(5)]
        curator = SkillCurator(collector, config)
        result = curator.run(skills, force=True)
        lru_transitions = [t for t in result.transitions if t.reason_type == "lru_eviction"]
        assert len(lru_transitions) == 0


# ── Error resilience ─────────────────────────────────────────────────────


class TestErrorResilience:
    def test_skill_without_storage_path_records_error(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7)
        skill = _make_skill("no_path", last_used_days_ago=100, storage_path=None)
        skill.storage_path = None
        curator = SkillCurator(collector, config)
        result = curator.run([skill], force=True)
        assert len(result.errors) > 0

    def test_sweep_continues_after_individual_error(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7)
        bad_skill = _make_skill("bad", last_used_days_ago=100, storage_path=None)
        bad_skill.storage_path = None
        good_skill = _make_skill("good", last_used_days_ago=100)
        curator = SkillCurator(collector, config)
        result = curator.run([bad_skill, good_skill], force=True)
        assert result.skills_scanned == 2


# ── Result types ─────────────────────────────────────────────────────────


class TestProperties:
    def test_config_property(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=42)
        curator = SkillCurator(collector, config)
        assert curator.config.stale_after_days == 42

    def test_enabled_property(self, collector: SkillStatsCollector) -> None:
        curator_on = SkillCurator(collector, CuratorConfig(enabled=True))
        curator_off = SkillCurator(collector, CuratorConfig(enabled=False))
        assert curator_on.enabled is True
        assert curator_off.enabled is False

    def test_consolidation_available_false_by_default(self, collector: SkillStatsCollector) -> None:
        curator = SkillCurator(collector)
        assert curator.consolidation_available is False

    def test_consolidation_available_true_when_deps_present(self, collector: SkillStatsCollector) -> None:
        from unittest.mock import MagicMock
        config = CuratorConfig(consolidation_enabled=True)
        curator = SkillCurator(
            collector,
            config,
            embedding_service=MagicMock(),
            llm=MagicMock(),
            write_backend=MagicMock(),
        )
        assert curator.consolidation_available is True


class TestAsyncSweep:
    @pytest.mark.asyncio
    async def test_run_async_without_consolidation(self, collector: SkillStatsCollector) -> None:
        config = CuratorConfig(stale_after_days=7)
        skills = [_make_skill("old", last_used_days_ago=100)]
        curator = SkillCurator(collector, config)
        lifecycle_result, consolidation_result = await curator.run_async(skills, force=True)
        assert lifecycle_result.skills_scanned == 1
        assert consolidation_result is None

    @pytest.mark.asyncio
    async def test_run_async_with_consolidation_dry_run(self, collector: SkillStatsCollector) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch
        config = CuratorConfig(consolidation_enabled=True, stale_after_days=365)
        skills = [_make_skill(f"skill_{i}") for i in range(5)]
        mock_embed = MagicMock()
        mock_llm = MagicMock()
        mock_backend = MagicMock()
        curator = SkillCurator(
            collector,
            config,
            embedding_service=mock_embed,
            llm=mock_llm,
            write_backend=mock_backend,
        )
        with patch(
            "myrm_agent_harness.agent.skills.curator.engine.SkillCurator._run_consolidation",
            new_callable=AsyncMock,
            return_value=None,
        ):
            lifecycle_result, _ = await curator.run_async(skills, force=True)
            assert lifecycle_result.skills_scanned == 5

    @pytest.mark.asyncio
    async def test_run_consolidation_returns_none_when_unavailable(self, collector: SkillStatsCollector) -> None:
        curator = SkillCurator(collector)
        result = await curator._run_consolidation([])
        assert result is None


class TestResultTypes:
    def test_curator_run_result_properties(self) -> None:
        result = CuratorRunResult(
            transitions=[
                CuratorTransition(
                    skill_name="a",
                    skill_path="/a",
                    from_status="active",
                    to_status="stale",
                    reason_type="inactive",
                    reason_message="test",
                    timestamp=datetime.now(UTC),
                ),
                CuratorTransition(
                    skill_name="b",
                    skill_path="/b",
                    from_status="stale",
                    to_status="archived",
                    reason_type="archive",
                    reason_message="test",
                    timestamp=datetime.now(UTC),
                ),
            ],
            skills_scanned=5,
            skipped_pinned=1,
        )
        assert result.total_transitions == 2
        assert result.stale_count == 1
        assert result.archived_count == 1
        assert result.skipped_pinned == 1


# ── Stats collector lifecycle integration ────────────────────────────────


class TestStatsCollectorLifecycle:
    def test_record_usage_auto_recovers_stale_to_active(self, tmp_skills_dir: Path) -> None:
        skill_dir = tmp_skills_dir / "stale_skill"
        skill_dir.mkdir()
        stats_file = skill_dir / ".stats.json"
        stats_file.write_text(
            json.dumps(
                {
                    "call_count": 5,
                    "success_count": 3,
                    "failure_count": 2,
                    "lifecycle_status": "stale",
                    "pinned": False,
                }
            )
        )

        collector = SkillStatsCollector(tmp_skills_dir)
        collector.record_usage(skill_dir, success=True, duration_ms=100.0)
        collector.flush()

        refreshed = collector.get_stats(skill_dir)
        assert refreshed.lifecycle_status == SkillLifecycleStatus.ACTIVE
        assert refreshed.call_count == 6

    def test_set_pinned_persists(self, tmp_skills_dir: Path) -> None:
        skill_dir = tmp_skills_dir / "pin_test"
        skill_dir.mkdir()

        collector = SkillStatsCollector(tmp_skills_dir)
        collector.set_pinned(skill_dir, pinned=True)
        stats = collector.get_stats(skill_dir)
        assert stats.pinned is True

        collector.set_pinned(skill_dir, pinned=False)
        stats = collector.get_stats(skill_dir)
        assert stats.pinned is False

    def test_update_lifecycle_status_persists(self, tmp_skills_dir: Path) -> None:
        skill_dir = tmp_skills_dir / "lifecycle_test"
        skill_dir.mkdir()

        collector = SkillStatsCollector(tmp_skills_dir)
        collector.update_lifecycle_status(skill_dir, SkillLifecycleStatus.ARCHIVED)
        stats = collector.get_stats(skill_dir)
        assert stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED
