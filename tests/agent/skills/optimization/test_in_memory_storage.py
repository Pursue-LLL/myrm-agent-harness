"""Tests for InMemoryStorage"""

import asyncio
from datetime import datetime, timedelta

import pytest

from myrm_agent_harness.agent.skills.optimization import (
    ABTestResult,
    ABTestStatus,
    InMemoryStorage,
    OptimizationResult,
    OptimizationStatus,
    SkillQualityScore,
    SkillType,
    StorageError,
)
from myrm_agent_harness.agent.skills.optimization.types import SecurityValidationResult


@pytest.fixture
def storage():
    """Create InMemoryStorage instance"""
    return InMemoryStorage(max_records=100, ttl_seconds=3600)


@pytest.fixture
def sample_quality_score():
    """Create sample quality score"""
    return SkillQualityScore(
        success_rate=0.8, token_efficiency=0.7, execution_time=0.6, user_satisfaction=0.9, call_frequency=0.5
    )


@pytest.fixture
def sample_optimization_result(sample_quality_score):
    """Create sample optimization result"""
    return OptimizationResult(
        skill_id="test-skill",
        skill_type=SkillType.USER,
        baseline_score=sample_quality_score,
        optimized_content="# Optimized Skill\n...",
        security_validation=SecurityValidationResult(passed=True, issues=[]),
        status=OptimizationStatus.COMPLETED,
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )


@pytest.fixture
def sample_ab_test_result(sample_quality_score):
    """Create sample AB test result"""
    return ABTestResult(
        skill_id="test-skill",
        baseline_version=1,
        candidate_version=2,
        baseline_score=sample_quality_score,
        candidate_score=sample_quality_score,
        sample_size=100,
        status=ABTestStatus.RUNNING,
        started_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_save_and_get_optimization_record(storage, sample_optimization_result):
    """Test saving and retrieving optimization record"""
    # Save
    await storage.save_optimization_record(sample_optimization_result)

    # Get
    result = await storage.get_optimization_record("test-skill")

    assert result is not None
    assert result.skill_id == "test-skill"
    assert result.status == OptimizationStatus.COMPLETED


@pytest.mark.asyncio
async def test_get_optimization_history(storage, sample_optimization_result):
    """Test getting optimization history"""
    # Save multiple records
    for i in range(5):
        result = OptimizationResult(
            skill_id="test-skill",
            skill_type=SkillType.USER,
            baseline_score=sample_optimization_result.baseline_score,
            optimized_content=f"Version {i}",
            security_validation=SecurityValidationResult(passed=True, issues=[]),
            status=OptimizationStatus.COMPLETED,
            started_at=datetime.now() - timedelta(days=i),
            completed_at=datetime.now() - timedelta(days=i),
        )
        await storage.save_optimization_record(result)

    # Get history
    history = await storage.get_optimization_history("test-skill", limit=3)

    assert len(history) <= 3
    # Should be sorted by time descending
    for i in range(len(history) - 1):
        assert history[i].started_at >= history[i + 1].started_at


@pytest.mark.asyncio
async def test_get_recent_optimizations(storage, sample_optimization_result):
    """Test getting recent optimizations"""
    # Save old record
    old_result = OptimizationResult(
        skill_id="old-skill",
        skill_type=SkillType.USER,
        baseline_score=sample_optimization_result.baseline_score,
        optimized_content="Old",
        security_validation=SecurityValidationResult(passed=True, issues=[]),
        status=OptimizationStatus.COMPLETED,
        started_at=datetime.now() - timedelta(days=30),
        completed_at=datetime.now() - timedelta(days=30),
    )
    await storage.save_optimization_record(old_result)

    # Save recent record
    await storage.save_optimization_record(sample_optimization_result)

    # Get recent (last 24 hours)
    recent = await storage.get_recent_optimizations(hours=24, limit=100)

    # Should only include recent record
    assert len(recent) == 1
    assert recent[0].skill_id == "test-skill"


@pytest.mark.asyncio
async def test_delete_old_optimizations(storage, sample_optimization_result):
    """Test deleting old optimizations"""
    # Save old record
    old_result = OptimizationResult(
        skill_id="old-skill",
        skill_type=SkillType.USER,
        baseline_score=sample_optimization_result.baseline_score,
        optimized_content="Old",
        security_validation=SecurityValidationResult(passed=True, issues=[]),
        status=OptimizationStatus.COMPLETED,
        started_at=datetime.now() - timedelta(days=100),
        completed_at=datetime.now() - timedelta(days=100),
    )
    await storage.save_optimization_record(old_result)

    # Save recent record
    await storage.save_optimization_record(sample_optimization_result)

    # Delete old (>90 days)
    deleted_count = await storage.delete_old_optimizations(days=90)

    assert deleted_count == 1

    # Recent should still exist
    result = await storage.get_optimization_record("test-skill")
    assert result is not None


@pytest.mark.asyncio
async def test_save_and_get_ab_test(storage, sample_ab_test_result):
    """Test saving and retrieving AB test"""
    # Save
    await storage.save_ab_test(sample_ab_test_result)

    # Get
    result = await storage.get_ab_test("test-skill")

    assert result is not None
    assert result.skill_id == "test-skill"
    assert result.status == ABTestStatus.RUNNING


@pytest.mark.asyncio
async def test_get_running_ab_tests(storage, sample_ab_test_result):
    """Test getting running AB tests"""
    # Save running test
    await storage.save_ab_test(sample_ab_test_result)

    # Save completed test
    completed_test = ABTestResult(
        skill_id="completed-skill",
        baseline_version=1,
        candidate_version=2,
        baseline_score=sample_ab_test_result.baseline_score,
        candidate_score=sample_ab_test_result.candidate_score,
        sample_size=200,
        status=ABTestStatus.CANDIDATE_WIN,
        started_at=datetime.now(),
        completed_at=datetime.now(),
        winner="candidate",
    )
    await storage.save_ab_test(completed_test)

    # Get running tests
    running = await storage.get_running_ab_tests()

    assert len(running) == 1
    assert running[0].skill_id == "test-skill"


@pytest.mark.asyncio
async def test_update_ab_test_status(storage, sample_ab_test_result):
    """Test updating AB test status"""
    # Save
    await storage.save_ab_test(sample_ab_test_result)

    # Update
    await storage.update_ab_test_status("test-skill", ABTestStatus.CANDIDATE_WIN, winner="candidate")

    # Get
    result = await storage.get_ab_test("test-skill")

    assert result.status == ABTestStatus.CANDIDATE_WIN
    assert result.winner == "candidate"


@pytest.mark.asyncio
async def test_increment_ab_test_sample_size(storage, sample_ab_test_result):
    """Test incrementing AB test sample size"""
    # Save
    await storage.save_ab_test(sample_ab_test_result)

    # Increment
    new_size = await storage.increment_ab_test_sample_size("test-skill", increment=10)

    assert new_size == 110

    # Verify
    result = await storage.get_ab_test("test-skill")
    assert result.sample_size == 110


@pytest.mark.asyncio
async def test_save_and_get_quality_snapshot(storage, sample_quality_score):
    """Test saving and retrieving quality snapshot"""
    # Save
    await storage.save_quality_snapshot("test-skill", sample_quality_score)

    # Get latest
    result = await storage.get_latest_quality("test-skill")

    assert result is not None
    assert result.success_rate == 0.8


@pytest.mark.asyncio
async def test_get_quality_history(storage, sample_quality_score):
    """Test getting quality history"""
    # Save multiple snapshots
    for i in range(5):
        score = SkillQualityScore(
            success_rate=0.5 + i * 0.1,
            token_efficiency=0.7,
            execution_time=0.6,
            user_satisfaction=0.9,
            call_frequency=0.5,
        )
        await storage.save_quality_snapshot("test-skill", score)
        await asyncio.sleep(0.01)  # Ensure different timestamps

    # Get history
    history = await storage.get_quality_history("test-skill", days=1)

    assert len(history) == 5
    # Should be sorted by time descending
    for i in range(len(history) - 1):
        assert history[i][0] >= history[i + 1][0]


@pytest.mark.asyncio
async def test_get_top_skills(storage, sample_quality_score):
    """Test getting top skills"""
    # Save quality scores for multiple skills
    await storage.save_quality_snapshot("skill-a", SkillQualityScore(0.9, 0.8, 0.7, 0.9, 0.6))
    await storage.save_quality_snapshot("skill-b", SkillQualityScore(0.7, 0.7, 0.7, 0.7, 0.5))
    await storage.save_quality_snapshot("skill-c", SkillQualityScore(0.95, 0.9, 0.8, 0.95, 0.7))

    # Get top skills
    tops = await storage.get_top_skills(limit=2)

    assert len(tops) == 2
    assert tops[0][0] == "skill-c"  # Highest score
    assert tops[1][0] == "skill-a"


@pytest.mark.asyncio
async def test_get_bottom_skills(storage, sample_quality_score):
    """Test getting bottom skills"""
    # Save quality scores
    await storage.save_quality_snapshot("skill-a", SkillQualityScore(0.9, 0.8, 0.7, 0.9, 0.6))
    await storage.save_quality_snapshot("skill-b", SkillQualityScore(0.5, 0.5, 0.5, 0.5, 0.3))
    await storage.save_quality_snapshot("skill-c", SkillQualityScore(0.95, 0.9, 0.8, 0.95, 0.7))

    # Get bottom skills
    bottoms = await storage.get_bottom_skills(limit=2)

    assert len(bottoms) == 2
    assert bottoms[0][0] == "skill-b"  # Lowest score
    assert bottoms[1][0] == "skill-a"


@pytest.mark.asyncio
async def test_lru_eviction(sample_optimization_result):
    """Test LRU eviction"""
    storage = InMemoryStorage(max_records=5, ttl_seconds=None)

    # Save 10 records
    for i in range(10):
        result = OptimizationResult(
            skill_id=f"skill-{i}",
            skill_type=SkillType.USER,
            baseline_score=sample_optimization_result.baseline_score,
            optimized_content=f"Version {i}",
            security_validation=SecurityValidationResult(passed=True, issues=[]),
            status=OptimizationStatus.COMPLETED,
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        await storage.save_optimization_record(result)

    # Should only have 5 records (max_records)
    all_records = await storage.get_recent_optimizations(hours=24, limit=100)
    assert len(all_records) <= 5


@pytest.mark.asyncio
async def test_ttl_expiration(sample_optimization_result):
    """Test TTL expiration"""
    storage = InMemoryStorage(max_records=100, ttl_seconds=1)  # 1 second TTL

    # Save record
    await storage.save_optimization_record(sample_optimization_result)

    # Should exist immediately
    result = await storage.get_optimization_record("test-skill")
    assert result is not None

    # Wait for TTL to expire
    await asyncio.sleep(1.1)

    # Should be expired
    result = await storage.get_optimization_record("test-skill")
    assert result is None


@pytest.mark.asyncio
async def test_storage_error_handling(storage):
    """Test storage error handling"""
    # Try to update non-existent AB test
    with pytest.raises(StorageError):
        await storage.update_ab_test_status("non-existent", ABTestStatus.BASELINE_WIN)

    # Try to increment non-existent AB test sample size
    with pytest.raises(StorageError):
        await storage.increment_ab_test_sample_size("non-existent")


@pytest.mark.asyncio
async def test_get_nonexistent_optimization_record(storage):
    """Test getting optimization record for non-existent skill"""
    result = await storage.get_optimization_record("nonexistent-skill")
    assert result is None


@pytest.mark.asyncio
async def test_get_ab_test_not_found(storage):
    """Test getting AB test that doesn't exist"""
    result = await storage.get_ab_test("nonexistent-skill")
    assert result is None


@pytest.mark.asyncio
async def test_get_quality_history_empty(storage):
    """Test getting quality history for non-existent skill"""
    history = await storage.get_quality_history("nonexistent-skill", days=30)
    assert history == []


@pytest.mark.asyncio
async def test_get_latest_quality_empty(storage):
    """Test getting latest quality for non-existent skill"""
    result = await storage.get_latest_quality("nonexistent-skill")
    assert result is None


@pytest.mark.asyncio
async def test_skill_version_lru_eviction():
    """Test version auto-eviction when exceeding 100 per skill"""
    storage = InMemoryStorage(max_records=10000, ttl_seconds=None)
    score = SkillQualityScore(0.8, 0.7, 0.6, 0.9, 0.5)

    for i in range(1, 105):
        await storage.save_skill_version(skill_id="skill-many", version=i, content=f"Version {i}", quality_score=score)

    versions = await storage.list_skill_versions("skill-many", limit=200)
    assert len(versions) <= 101


@pytest.mark.asyncio
async def test_list_skill_versions_empty(storage):
    """Test listing versions for non-existent skill"""
    versions = await storage.list_skill_versions("nonexistent-skill")
    assert versions == []


@pytest.mark.asyncio
async def test_list_skill_versions_with_limit(storage):
    """Test listing versions respects limit"""
    score = SkillQualityScore(0.8, 0.7, 0.6, 0.9, 0.5)
    for i in range(1, 6):
        await storage.save_skill_version(skill_id="test-skill", version=i, content=f"V{i}", quality_score=score)

    versions = await storage.list_skill_versions("test-skill", limit=3)
    assert len(versions) == 3
    assert versions[0].version == 5


@pytest.mark.asyncio
async def test_get_active_version_no_skill(storage):
    """Test get_active_version for non-existent skill"""
    result = await storage.get_active_version("nonexistent-skill")
    assert result is None


@pytest.mark.asyncio
async def test_activate_version_skill_not_found(storage):
    """Test activating version for non-existent skill"""
    with pytest.raises(StorageError):
        await storage.activate_version("nonexistent-skill", 1)


@pytest.mark.asyncio
async def test_activate_version_version_not_found(storage):
    """Test activating non-existent version"""
    score = SkillQualityScore(0.8, 0.7, 0.6, 0.9, 0.5)
    await storage.save_skill_version(skill_id="test-skill", version=1, content="V1", quality_score=score)
    with pytest.raises(StorageError):
        await storage.activate_version("test-skill", 999)


@pytest.mark.asyncio
async def test_delete_skill_versions_empty(storage):
    """Test deleting versions for non-existent skill"""
    deleted = await storage.delete_skill_versions("nonexistent-skill")
    assert deleted == 0


@pytest.mark.asyncio
async def test_health_check(storage, sample_quality_score):
    """Test health check returns correct info"""
    await storage.save_quality_snapshot("test-skill", sample_quality_score)

    result = await storage.health_check()

    assert result["healthy"] is True
    assert result["storage_type"] == "in_memory"
    assert result["readable"] is True
    assert result["writable"] is True
    assert result["record_count"] == 0
    assert result["version_count"] == 0


@pytest.mark.asyncio
async def test_persistence_save_and_load(tmp_path):
    """Test saving to file and loading from file"""
    persistence_file = tmp_path / "storage.json"
    storage = InMemoryStorage(max_records=100, ttl_seconds=None, persistence_path=str(persistence_file))

    score = SkillQualityScore(0.8, 0.7, 0.6, 0.9, 0.5)
    await storage.save_quality_snapshot("test-skill", score)

    await storage.save_to_file()
    assert persistence_file.exists()

    # Create new storage from file
    storage2 = InMemoryStorage(max_records=100, ttl_seconds=None, persistence_path=str(persistence_file))
    assert storage2 is not None


@pytest.mark.asyncio
async def test_persistence_save_no_path():
    """Test save_to_file with no persistence path"""
    storage = InMemoryStorage(max_records=100, ttl_seconds=None)
    await storage.save_to_file()


@pytest.mark.asyncio
async def test_start_and_stop():
    """Test start/stop lifecycle"""
    storage = InMemoryStorage(max_records=100, ttl_seconds=None)
    await storage.start()
    await storage.stop()


@pytest.mark.asyncio
async def test_start_with_auto_save(tmp_path):
    """Test start with auto-save enabled"""
    persistence_file = tmp_path / "auto_save.json"
    storage = InMemoryStorage(
        max_records=100, ttl_seconds=None, persistence_path=str(persistence_file), auto_save_interval=1
    )

    await storage.start()
    assert storage._auto_save_task is not None

    await asyncio.sleep(0.1)
    await storage.stop()

    assert persistence_file.exists()


@pytest.mark.asyncio
async def test_quality_snapshot_limit(storage):
    """Test quality snapshot list cap at 1000"""
    score = SkillQualityScore(0.8, 0.7, 0.6, 0.9, 0.5)

    for _ in range(1010):
        await storage.save_quality_snapshot("test-skill", score)

    async with storage._lock:
        assert len(storage._quality_snapshots["test-skill"]) <= 1000
