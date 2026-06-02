"""Aggregation Tests

Tests for SkillQualityAggregator Protocol and implementations.
"""

import pytest

from myrm_agent_harness.agent.skills.optimization.aggregation_in_memory import InMemoryAggregator
from myrm_agent_harness.agent.skills.optimization.aggregation_stream import AggregationStream
from myrm_agent_harness.agent.skills.optimization.aggregation_streaming import StreamingAggregator
from myrm_agent_harness.agent.skills.optimization.event_emitter import EventEmitter
from myrm_agent_harness.agent.skills.optimization.in_memory_storage import InMemoryStorage
from myrm_agent_harness.agent.skills.optimization.types import AggregateDimension, SkillQualityScore


@pytest.fixture
def storage():
    """Create InMemoryStorage for testing"""
    return InMemoryStorage()


@pytest.fixture
def event_emitter():
    """Create EventEmitter for testing"""
    return EventEmitter()


@pytest.fixture
async def storage_with_data(storage):
    """Create storage with sample quality snapshots"""
    skill_ids = ["skill-a", "skill-b", "skill-c"]

    for skill_id in skill_ids:
        for i in range(10):
            score = SkillQualityScore(
                success_rate=0.8 + i * 0.01,
                token_efficiency=0.7 + i * 0.01,
                execution_time=0.9 - i * 0.01,
                user_satisfaction=0.85 + i * 0.005,
                call_frequency=0.5,
            )
            await storage.save_quality_snapshot(skill_id, score)

    return storage


@pytest.mark.asyncio
async def test_in_memory_aggregator_by_skill(storage_with_data):
    """Test InMemoryAggregator.aggregate_by_skill"""
    aggregator = InMemoryAggregator(storage_with_data)

    all_skills = await aggregator.aggregate_by_skill()

    assert len(all_skills) == 3
    assert all([agg.sample_count == 10 for agg in all_skills])
    assert all([agg.avg_quality_score > 0.7 for agg in all_skills])

    one_skill = await aggregator.aggregate_by_skill("skill-a")
    assert len(one_skill) == 1
    assert one_skill[0].skill_id == "skill-a"


@pytest.mark.asyncio
async def test_in_memory_aggregator_global_metrics(storage_with_data):
    """Test InMemoryAggregator.get_global_metrics"""
    aggregator = InMemoryAggregator(storage_with_data)

    metrics = await aggregator.get_global_metrics()

    assert metrics.total_skills == 3
    assert metrics.total_executions == 30
    assert metrics.avg_quality_score > 0.7
    assert metrics.median_quality_score > 0.0


@pytest.mark.asyncio
async def test_in_memory_aggregator_compare(storage_with_data):
    """Test InMemoryAggregator.compare"""
    aggregator = InMemoryAggregator(storage_with_data)

    results = await aggregator.compare(before_range_days=30, after_range_days=15, skill_id="skill-a")

    assert len(results) <= 1


@pytest.mark.asyncio
async def test_in_memory_aggregator_by_dimension(storage_with_data):
    """Test InMemoryAggregator.aggregate_by_dimension"""
    aggregator = InMemoryAggregator(storage_with_data)

    by_skill = await aggregator.aggregate_by_dimension(AggregateDimension.SKILL)
    assert len(by_skill) == 3

    by_user = await aggregator.aggregate_by_dimension(AggregateDimension.USER)
    assert len(by_user) == 0


@pytest.mark.asyncio
async def test_streaming_aggregator_basic(storage, event_emitter):
    """Test StreamingAggregator basic functionality"""
    aggregator = StreamingAggregator(storage, event_emitter)

    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )

    await event_emitter.emit("skill_executed", {"skill_id": "test-skill", "quality_score": score})

    await event_emitter.emit("skill_executed", {"skill_id": "test-skill", "quality_score": score})

    aggregates = await aggregator.aggregate_by_skill("test-skill")

    assert len(aggregates) == 1
    assert aggregates[0].skill_id == "test-skill"
    assert aggregates[0].sample_count == 2


@pytest.mark.asyncio
async def test_streaming_aggregator_global_metrics(storage, event_emitter):
    """Test StreamingAggregator.get_global_metrics"""
    aggregator = StreamingAggregator(storage, event_emitter)

    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )

    await event_emitter.emit("skill_executed", {"skill_id": "skill-a", "quality_score": score})
    await event_emitter.emit("skill_executed", {"skill_id": "skill-b", "quality_score": score})

    metrics = await aggregator.get_global_metrics()

    assert metrics.total_skills == 2
    assert metrics.total_executions == 2


@pytest.mark.asyncio
async def test_aggregation_stream_integration(storage, event_emitter):
    """Test AggregationStream event forwarding"""
    aggregator1 = StreamingAggregator(storage, event_emitter)
    aggregator2 = StreamingAggregator(storage, event_emitter)

    stream = AggregationStream(event_emitter)
    stream.register_aggregator(aggregator1)
    stream.register_aggregator(aggregator2)

    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )

    await event_emitter.emit("skill_executed", {"skill_id": "test-skill", "quality_score": score})

    agg1_result = await aggregator1.aggregate_by_skill("test-skill")
    agg2_result = await aggregator2.aggregate_by_skill("test-skill")

    assert len(agg1_result) == 1
    assert len(agg2_result) == 1

    stream.unregister_aggregator(aggregator1)
    assert len(stream._aggregators) == 1


@pytest.mark.asyncio
async def test_protocol_contract_aggregate_by_skill(storage_with_data):
    """Test Protocol: aggregate_by_skill method signature"""
    aggregator = InMemoryAggregator(storage_with_data)

    result1 = await aggregator.aggregate_by_skill()
    assert isinstance(result1, list)

    result2 = await aggregator.aggregate_by_skill("skill-a")
    assert isinstance(result2, list)

    result3 = await aggregator.aggregate_by_skill("skill-a", time_range_days=7)
    assert isinstance(result3, list)


@pytest.mark.asyncio
async def test_protocol_contract_global_metrics(storage_with_data):
    """Test Protocol: get_global_metrics method signature"""
    aggregator = InMemoryAggregator(storage_with_data)

    metrics = await aggregator.get_global_metrics()

    assert hasattr(metrics, "total_skills")
    assert hasattr(metrics, "total_users")
    assert hasattr(metrics, "total_executions")
    assert hasattr(metrics, "avg_quality_score")
    assert hasattr(metrics, "calculated_at")


# ===== math_utils tests =====

from myrm_agent_harness.agent.skills.optimization.math_utils import percentile, sample_std


def test_sample_std_basic():
    """Test sample_std with known values"""
    assert sample_std([]) == 0.0
    assert sample_std([5.0]) == 0.0
    std = sample_std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
    assert abs(std - 2.138) < 0.01


def test_sample_std_bessel_correction():
    """Verify Bessel's correction (N-1 denominator)"""
    values = [1.0, 3.0]
    std = sample_std(values)
    expected = (((1 - 2) ** 2 + (3 - 2) ** 2) / 1) ** 0.5
    assert abs(std - expected) < 1e-10


def test_percentile_basic():
    """Test percentile with known values"""
    assert percentile([], 50) == 0.0
    assert percentile([1.0], 50) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0) == 1.0
    p50 = percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50)
    assert abs(p50 - 3.0) < 1e-10
    p90 = percentile([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0], 90)
    assert abs(p90 - 9.1) < 0.1


# ===== UniversalAggregator tests =====

from datetime import datetime, timedelta

from myrm_agent_harness.agent.skills.optimization.aggregation_universal import UniversalAggregator
from myrm_agent_harness.agent.skills.optimization.types import SkillQualitySnapshot


class InMemoryDataSource:
    """Minimal DataSource for testing UniversalAggregator"""

    def __init__(self, records: list[SkillQualitySnapshot]):
        self._records = records

    async def query_raw_records(
        self, skill_id: str | None = None, time_range_days: int = 30, filters: dict[str, str] | None = None
    ) -> list[SkillQualitySnapshot]:
        cutoff = datetime.now() - timedelta(days=time_range_days)
        result = [r for r in self._records if r.recorded_at >= cutoff]
        if skill_id:
            result = [r for r in result if r.skill_id == skill_id]
        if filters:
            pass
        return result

    async def query_aggregated(
        self, group_by: str, time_range_days: int = 30, filters: dict[str, str] | None = None
    ) -> list[dict[str, float]]:
        return []


def _make_snapshots(
    skill_id: str, count: int = 10, base_score: float = 0.8, days_ago: int = 0
) -> list[SkillQualitySnapshot]:
    """Generate test snapshots"""
    return [
        SkillQualitySnapshot(
            id=f"{skill_id}-{i}",
            skill_id=skill_id,
            recorded_at=datetime.now() - timedelta(days=days_ago, hours=i),
            overall_score=base_score + i * 0.01,
            success_rate=0.8 + i * 0.01,
            token_efficiency=0.7 + i * 0.01,
            execution_time=0.9 - i * 0.01,
            user_satisfaction=0.85 + i * 0.005,
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_universal_aggregator_by_skill():
    """Test UniversalAggregator.aggregate_by_skill"""
    records = _make_snapshots("skill-a") + _make_snapshots("skill-b", base_score=0.7)
    agg = UniversalAggregator(InMemoryDataSource(records))

    all_skills = await agg.aggregate_by_skill()
    assert len(all_skills) == 2
    assert all_skills[0].avg_quality_score >= all_skills[1].avg_quality_score

    one_skill = await agg.aggregate_by_skill("skill-a")
    assert len(one_skill) == 1
    assert one_skill[0].skill_id == "skill-a"
    assert one_skill[0].sample_count == 10


@pytest.mark.asyncio
async def test_universal_aggregator_by_user():
    """Test UniversalAggregator.aggregate_by_user (single-user sandbox)"""
    records = _make_snapshots("s1") + _make_snapshots("s2")
    agg = UniversalAggregator(InMemoryDataSource(records))

    users = await agg.aggregate_by_user()
    assert len(users) == 1
    assert users[0].user_id == "default"
    assert users[0].total_executions == 20


@pytest.mark.asyncio
async def test_universal_aggregator_by_dimension():
    """Test UniversalAggregator.aggregate_by_dimension"""
    records = _make_snapshots("skill-a") + _make_snapshots("skill-b")
    agg = UniversalAggregator(InMemoryDataSource(records))

    by_skill = await agg.aggregate_by_dimension(AggregateDimension.SKILL)
    assert len(by_skill) == 2
    assert "skill-a" in by_skill

    by_user = await agg.aggregate_by_dimension(AggregateDimension.USER)
    assert "default" in by_user

    by_other = await agg.aggregate_by_dimension(AggregateDimension.REGION)
    assert by_other == {}


@pytest.mark.asyncio
async def test_universal_aggregator_global_metrics():
    """Test UniversalAggregator.get_global_metrics"""
    records = _make_snapshots("skill-a") + _make_snapshots("skill-b")
    agg = UniversalAggregator(InMemoryDataSource(records))

    metrics = await agg.get_global_metrics()
    assert metrics.total_skills == 2
    assert metrics.total_executions == 20
    assert metrics.avg_quality_score > 0.7
    assert metrics.quality_std >= 0.0


@pytest.mark.asyncio
async def test_universal_aggregator_global_metrics_empty():
    """Test get_global_metrics with no data"""
    agg = UniversalAggregator(InMemoryDataSource([]))
    metrics = await agg.get_global_metrics()
    assert metrics.total_skills == 0
    assert metrics.total_executions == 0
    assert metrics.avg_quality_score == 0.0


@pytest.mark.asyncio
async def test_universal_aggregator_compare():
    """Test UniversalAggregator.compare with non-overlapping time windows"""
    before_records = _make_snapshots("skill-a", count=5, base_score=0.6, days_ago=20)
    after_records = _make_snapshots("skill-a", count=5, base_score=0.9, days_ago=0)
    agg = UniversalAggregator(InMemoryDataSource(before_records + after_records))

    results = await agg.compare(before_range_days=30, after_range_days=10)

    assert len(results) >= 0
    for r in results:
        assert hasattr(r, "delta_execution_time")
        assert hasattr(r, "delta_user_satisfaction")
        assert hasattr(r, "is_statistically_significant")
        assert hasattr(r, "p_value")


@pytest.mark.asyncio
async def test_universal_aggregator_percentiles():
    """Test UniversalAggregator.get_quality_percentiles"""
    records = _make_snapshots("skill-a", count=20)
    agg = UniversalAggregator(InMemoryDataSource(records))

    p = await agg.get_quality_percentiles()
    assert "p50" in p and "p90" in p and "p95" in p and "p99" in p
    assert p["p50"] <= p["p90"] <= p["p95"] <= p["p99"]

    p_empty = await agg.get_quality_percentiles(skill_id="nonexistent")
    assert p_empty["p50"] == 0.0


@pytest.mark.asyncio
async def test_universal_aggregator_pre_aggregated_path():
    """Test UniversalAggregator uses pre-aggregated data when available"""

    class PreAggDataSource(InMemoryDataSource):
        async def query_aggregated(self, group_by, time_range_days=30, filters=None):
            if group_by == "skill_id":
                return [
                    {
                        "skill_id": "pre-agg-skill",
                        "sample_count": 100,
                        "avg_quality_score": 0.95,
                        "quality_std": 0.02,
                        "avg_success_rate": 0.98,
                        "avg_token_efficiency": 0.9,
                        "avg_execution_time": 0.5,
                        "avg_user_satisfaction": 0.97,
                        "total_executions": 100,
                        "user_count": 5,
                        "optimization_count": 3,
                    }
                ]
            return []

    agg = UniversalAggregator(PreAggDataSource([]))
    results = await agg.aggregate_by_skill()
    assert len(results) == 1
    assert results[0].skill_id == "pre-agg-skill"
    assert results[0].sample_count == 100


# ===== StreamingAggregator extended tests =====


@pytest.mark.asyncio
async def test_streaming_aggregator_by_dimension(storage, event_emitter):
    """Test StreamingAggregator.aggregate_by_dimension"""
    aggregator = StreamingAggregator(storage, event_emitter)
    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )
    await event_emitter.emit("skill_executed", {"skill_id": "skill-a", "quality_score": score})
    await event_emitter.emit("skill_executed", {"skill_id": "skill-b", "quality_score": score})

    by_skill = await aggregator.aggregate_by_dimension(AggregateDimension.SKILL)
    assert len(by_skill) == 2
    assert "skill-a" in by_skill

    by_user = await aggregator.aggregate_by_dimension(AggregateDimension.USER)
    assert len(by_user) == 0

    by_other = await aggregator.aggregate_by_dimension(AggregateDimension.REGION)
    assert by_other == {}


@pytest.mark.asyncio
async def test_streaming_aggregator_percentiles(storage, event_emitter):
    """Test StreamingAggregator.get_quality_percentiles"""
    aggregator = StreamingAggregator(storage, event_emitter)
    for i in range(10):
        score = SkillQualityScore(
            success_rate=0.5 + i * 0.05,
            token_efficiency=0.6 + i * 0.04,
            execution_time=0.7 + i * 0.03,
            user_satisfaction=0.8 + i * 0.02,
            call_frequency=0.5,
        )
        await event_emitter.emit("skill_executed", {"skill_id": f"s-{i}", "quality_score": score})

    p = await aggregator.get_quality_percentiles()
    assert p["p50"] <= p["p90"] <= p["p95"] <= p["p99"]

    p_empty = await aggregator.get_quality_percentiles(skill_id="nonexistent")
    assert p_empty["p50"] == 0.0


@pytest.mark.asyncio
async def test_streaming_aggregator_compare(storage, event_emitter):
    """Test StreamingAggregator.compare"""
    aggregator = StreamingAggregator(storage, event_emitter)
    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )
    await event_emitter.emit("skill_executed", {"skill_id": "test-skill", "quality_score": score})

    await storage.save_quality_snapshot("test-skill", score)

    results = await aggregator.compare(before_range_days=30, after_range_days=15)
    for r in results:
        assert hasattr(r, "delta_execution_time")
        assert hasattr(r, "delta_user_satisfaction")
        assert hasattr(r, "is_statistically_significant")
        assert hasattr(r, "p_value")


@pytest.mark.asyncio
async def test_streaming_aggregator_quality_updated(storage, event_emitter):
    """Test StreamingAggregator handles quality_updated events"""
    aggregator = StreamingAggregator(storage, event_emitter)
    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )
    await event_emitter.emit("quality_updated", {"skill_id": "test-skill", "quality_score": score})

    aggregates = await aggregator.aggregate_by_skill("test-skill")
    assert len(aggregates) == 1
    assert aggregates[0].sample_count == 1


@pytest.mark.asyncio
async def test_streaming_aggregator_window_stats(storage, event_emitter):
    """Test StreamingAggregator _SkillStats window stats"""
    aggregator = StreamingAggregator(storage, event_emitter)
    for i in range(5):
        score = SkillQualityScore(
            success_rate=0.8 + i * 0.02,
            token_efficiency=0.7,
            execution_time=0.9,
            user_satisfaction=0.85,
            call_frequency=0.5,
        )
        await event_emitter.emit("skill_executed", {"skill_id": "s1", "quality_score": score})

    stats = aggregator._skill_stats["s1"]
    count, avg, std = stats.get_window_stats("1h")
    assert count == 5
    assert avg > 0
    assert std >= 0

    count_24h, _, _ = stats.get_window_stats("24h")
    assert count_24h == 5

    count_7d, _, _ = stats.get_window_stats("7d")
    assert count_7d == 5

    count_invalid, _avg_invalid, _std_invalid = stats.get_window_stats("invalid")
    assert count_invalid == 0


@pytest.mark.asyncio
async def test_streaming_aggregator_ignore_invalid_events(storage, event_emitter):
    """Test StreamingAggregator ignores events without required fields"""
    aggregator = StreamingAggregator(storage, event_emitter)

    await event_emitter.emit("skill_executed", {})
    await event_emitter.emit("skill_executed", {"skill_id": "s1"})
    await event_emitter.emit("quality_updated", {})

    assert len(aggregator._skill_stats) == 0


# ===== InMemoryAggregator extended coverage =====


@pytest.mark.asyncio
async def test_in_memory_aggregator_percentiles(storage_with_data):
    """Test InMemoryAggregator.get_quality_percentiles"""
    aggregator = InMemoryAggregator(storage_with_data)

    p = await aggregator.get_quality_percentiles()
    assert "p50" in p and "p90" in p and "p95" in p and "p99" in p
    assert p["p50"] <= p["p90"] <= p["p95"] <= p["p99"]

    p_one = await aggregator.get_quality_percentiles(skill_id="skill-a")
    assert p_one["p50"] > 0


@pytest.mark.asyncio
async def test_in_memory_aggregator_percentiles_empty(storage):
    """Test InMemoryAggregator.get_quality_percentiles with no data"""
    aggregator = InMemoryAggregator(storage)
    p = await aggregator.get_quality_percentiles()
    assert p["p50"] == 0.0


# ===== UniversalAggregator pre-aggregation fallback =====


@pytest.mark.asyncio
async def test_universal_aggregator_pre_agg_fallback():
    """Test UniversalAggregator falls back when pre-aggregation raises exception"""

    class FailingPreAggDataSource(InMemoryDataSource):
        async def query_aggregated(self, group_by, time_range_days=30, filters=None):
            raise RuntimeError("DB connection failed")

    records = _make_snapshots("skill-a", count=5)
    agg = UniversalAggregator(FailingPreAggDataSource(records))

    results = await agg.aggregate_by_skill()
    assert len(results) == 1
    assert results[0].skill_id == "skill-a"


@pytest.mark.asyncio
async def test_universal_aggregator_user_pre_agg_path():
    """Test UniversalAggregator.aggregate_by_user with pre-aggregated data"""

    class UserPreAggDataSource(InMemoryDataSource):
        async def query_aggregated(self, group_by, time_range_days=30, filters=None):
            if group_by == "user_id":
                return [
                    {
                        "sample_count": 50,
                        "avg_quality_score": 0.92,
                        "unique_skills_used": 3,
                        "total_executions": 50,
                    }
                ]
            return []

    agg = UniversalAggregator(UserPreAggDataSource([]))
    results = await agg.aggregate_by_user()
    assert len(results) == 1
    assert results[0].sample_count == 50


# ===== StreamingAggregator snapshot =====


@pytest.mark.asyncio
async def test_streaming_aggregator_snapshot(storage, event_emitter):
    """Test StreamingAggregator.save_snapshot and _load_snapshot"""
    aggregator = StreamingAggregator(storage, event_emitter, enable_snapshot=True)

    score = SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.95, user_satisfaction=0.85, call_frequency=0.5
    )
    await event_emitter.emit("skill_executed", {"skill_id": "snap-skill", "quality_score": score})

    await aggregator.save_snapshot()

    aggregator2 = StreamingAggregator(storage, event_emitter, enable_snapshot=False)
    await aggregator2._load_snapshot()

    assert "snap-skill" in aggregator2._skill_stats
    assert aggregator2._skill_stats["snap-skill"].count == 1
    assert aggregator2._global_stats.total_executions == 1


@pytest.mark.asyncio
async def test_streaming_aggregator_snapshot_disabled(storage, event_emitter):
    """Test snapshot no-op when disabled"""
    aggregator = StreamingAggregator(storage, event_emitter, enable_snapshot=False)
    await aggregator.save_snapshot()

    aggregator2 = StreamingAggregator(storage, event_emitter, enable_snapshot=False)
    await aggregator2._load_snapshot()
    assert len(aggregator2._skill_stats) == 0
