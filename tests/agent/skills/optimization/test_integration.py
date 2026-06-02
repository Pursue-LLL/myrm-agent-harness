"""Integration Tests for Skill Optimization System

Tests integration between major components:
1. Storage layer integration (versions + optimization records + A/B tests)
2. Security validation integration
3. A/B test engine with storage
"""

from datetime import datetime

import pytest

from myrm_agent_harness.agent.skills.optimization import (
    ABTestConfig,
    InMemoryStorage,
    OptimizationConfig,
    OptimizationResult,
    OptimizationStatus,
    SecurityConfig,
    SecurityValidationResult,
    SkillQualityScore,
    SkillType,
)


@pytest.fixture
def storage():
    """Test storage"""
    return InMemoryStorage(max_records=100, ttl_seconds=None)


@pytest.fixture
def config():
    """Test configuration"""
    return OptimizationConfig(
        ab_test=ABTestConfig(min_sample_size=5, max_sample_size=20),
        security=SecurityConfig(dangerous_patterns=[r"eval\(", r"exec\("], enable_sandbox_validation=False),
    )


@pytest.mark.asyncio
async def test_storage_integration_with_versions_and_optimization(storage):
    """Test storage integrates versions with optimization records"""

    # 1. Create an optimization result
    quality_score = SkillQualityScore(
        success_rate=0.85, token_efficiency=0.80, execution_time=0.75, user_satisfaction=0.70, call_frequency=0.65
    )

    optimization_result = OptimizationResult(
        skill_id="test-skill",
        skill_type=SkillType.PREBUILT,
        baseline_score=quality_score,
        optimized_content="# Optimized Skill\n\nImproved implementation",
        security_validation=SecurityValidationResult(passed=True, issues=[]),
        status=OptimizationStatus.COMPLETED,
        started_at=datetime.now(),
        completed_at=datetime.now(),
        version=1,
    )

    # 2. Save optimization record
    await storage.save_optimization_record(optimization_result)

    # 3. Save corresponding version
    await storage.save_skill_version(
        skill_id="test-skill",
        version=1,
        content=optimization_result.optimized_content,
        quality_score=quality_score,
        created_by="llm",
        optimization_id=optimization_result.started_at.isoformat(),
    )

    # 4. Verify linkage
    stored_opt = await storage.get_optimization_record("test-skill")
    assert stored_opt is not None
    assert stored_opt.version == 1

    stored_version = await storage.get_skill_version("test-skill", 1)
    assert stored_version is not None
    assert stored_version.content == optimization_result.optimized_content

    # 5. Activate version
    await storage.activate_version("test-skill", 1)
    active = await storage.get_active_version("test-skill")
    assert active is not None
    assert active.version == 1
    assert active.is_active is True


@pytest.mark.asyncio
async def test_quality_history_integration(storage):
    """Test quality history tracking integrates with versions"""

    quality_score_v1 = SkillQualityScore(
        success_rate=0.70, token_efficiency=0.65, execution_time=0.60, user_satisfaction=0.55, call_frequency=0.50
    )

    quality_score_v2 = SkillQualityScore(
        success_rate=0.85, token_efficiency=0.80, execution_time=0.75, user_satisfaction=0.70, call_frequency=0.65
    )

    # Save quality snapshots
    await storage.save_quality_snapshot("test-skill", quality_score_v1, version=1)
    await storage.save_quality_snapshot("test-skill", quality_score_v2, version=2)

    # Get history
    history = await storage.get_quality_history("test-skill", days=30)
    assert len(history) == 2

    # Get latest
    latest = await storage.get_latest_quality("test-skill")
    assert latest is not None
    assert latest.overall_score > quality_score_v1.overall_score

    # Get top skills
    top_skills = await storage.get_top_skills(limit=10)
    assert len(top_skills) > 0
    assert top_skills[0][0] == "test-skill"


@pytest.mark.asyncio
async def test_rollback_workflow_integration(storage):
    """Test complete rollback workflow"""

    # Simulate multiple optimizations
    for version in range(1, 4):
        quality_score = SkillQualityScore(
            success_rate=0.70 + (version * 0.05),
            token_efficiency=0.65 + (version * 0.05),
            execution_time=0.60 + (version * 0.05),
            user_satisfaction=0.55 + (version * 0.05),
            call_frequency=0.50 + (version * 0.05),
        )

        await storage.save_skill_version(
            skill_id="evolving-skill",
            version=version,
            content=f"# Version {version}\n\nImplementation v{version}",
            quality_score=quality_score,
            created_by="llm",
        )

    # Activate latest version (v3)
    await storage.activate_version("evolving-skill", 3)
    active = await storage.get_active_version("evolving-skill")
    assert active.version == 3

    # Rollback to v2
    rolled_back = await storage.activate_version("evolving-skill", 2)
    assert rolled_back.version == 2
    assert rolled_back.is_active is True

    # Verify v3 is no longer active
    v3 = await storage.get_skill_version("evolving-skill", 3)
    assert v3.is_active is False

    # List all versions
    all_versions = await storage.list_skill_versions("evolving-skill")
    assert len(all_versions) == 3
    assert all_versions[0].version == 3  # Sorted descending
    assert all_versions[1].version == 2
    assert all_versions[2].version == 1


@pytest.mark.asyncio
async def test_multi_skill_storage_integration(storage):
    """Test storage handles multiple skills correctly"""

    skills = ["skill-a", "skill-b", "skill-c"]

    for skill_id in skills:
        quality_score = SkillQualityScore(
            success_rate=0.80, token_efficiency=0.75, execution_time=0.70, user_satisfaction=0.65, call_frequency=0.60
        )

        # Save optimization record
        result = OptimizationResult(
            skill_id=skill_id,
            skill_type=SkillType.PREBUILT,
            baseline_score=quality_score,
            optimized_content=f"# {skill_id}\n\nOptimized",
            security_validation=SecurityValidationResult(passed=True, issues=[]),
            status=OptimizationStatus.COMPLETED,
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        await storage.save_optimization_record(result)

        # Save version
        await storage.save_skill_version(
            skill_id=skill_id, version=1, content=result.optimized_content, quality_score=quality_score
        )

        # Save quality snapshot
        await storage.save_quality_snapshot(skill_id, quality_score)

    # Verify each skill's data is isolated
    for skill_id in skills:
        opt = await storage.get_optimization_record(skill_id)
        assert opt is not None
        assert opt.skill_id == skill_id

        version = await storage.get_skill_version(skill_id, 1)
        assert version is not None
        assert version.skill_id == skill_id

        quality = await storage.get_latest_quality(skill_id)
        assert quality is not None

    # Get recent optimizations should return all
    recent = await storage.get_recent_optimizations(hours=24, limit=100)
    assert len(recent) >= 3
