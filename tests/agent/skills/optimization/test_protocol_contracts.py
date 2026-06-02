"""Protocol Contract Tests

Verify that implementations correctly satisfy Protocol contracts.
"""

import pytest

from myrm_agent_harness.agent.skills.optimization import InMemoryStorage, SkillOptimizationStorage


def test_in_memory_storage_implements_protocol():
    """Test that InMemoryStorage implements SkillOptimizationStorage Protocol"""
    storage = InMemoryStorage()

    # Use isinstance with runtime_checkable Protocol
    # Since SkillOptimizationStorage is Protocol, we check attributes
    assert hasattr(storage, "save_optimization_record")
    assert hasattr(storage, "get_optimization_record")
    assert hasattr(storage, "get_optimization_history")
    assert hasattr(storage, "get_recent_optimizations")
    assert hasattr(storage, "delete_old_optimizations")

    assert hasattr(storage, "save_ab_test")
    assert hasattr(storage, "get_ab_test")
    assert hasattr(storage, "get_running_ab_tests")
    assert hasattr(storage, "update_ab_test_status")
    assert hasattr(storage, "increment_ab_test_sample_size")

    assert hasattr(storage, "save_skill_version")
    assert hasattr(storage, "get_skill_version")
    assert hasattr(storage, "get_active_version")
    assert hasattr(storage, "list_skill_versions")
    assert hasattr(storage, "activate_version")
    assert hasattr(storage, "delete_skill_versions")

    assert hasattr(storage, "save_quality_snapshot")
    assert hasattr(storage, "get_quality_history")
    assert hasattr(storage, "get_latest_quality")
    assert hasattr(storage, "get_top_skills")
    assert hasattr(storage, "get_bottom_skills")


def test_in_memory_storage_methods_are_async():
    """Test that InMemoryStorage methods are async"""
    import inspect

    storage = InMemoryStorage()

    # Check that key methods are coroutines
    assert inspect.iscoroutinefunction(storage.save_optimization_record)
    assert inspect.iscoroutinefunction(storage.get_optimization_record)
    assert inspect.iscoroutinefunction(storage.save_ab_test)
    assert inspect.iscoroutinefunction(storage.get_ab_test)
    assert inspect.iscoroutinefunction(storage.save_skill_version)
    assert inspect.iscoroutinefunction(storage.get_skill_version)
    assert inspect.iscoroutinefunction(storage.get_active_version)
    assert inspect.iscoroutinefunction(storage.list_skill_versions)
    assert inspect.iscoroutinefunction(storage.activate_version)
    assert inspect.iscoroutinefunction(storage.delete_skill_versions)
    assert inspect.iscoroutinefunction(storage.save_quality_snapshot)
    assert inspect.iscoroutinefunction(storage.get_latest_quality)


def test_protocol_type_hints():
    """Test that Protocol has correct type hints"""

    # Get type hints from Protocol
    from myrm_agent_harness.agent.skills.optimization.protocols import SkillOptimizationStorage as StorageProtocol

    # Check that Protocol methods exist
    assert hasattr(StorageProtocol, "save_optimization_record")
    assert hasattr(StorageProtocol, "get_optimization_record")

    # Verify method signatures are documented
    save_method = StorageProtocol.save_optimization_record
    assert save_method.__doc__ is not None


def test_in_memory_storage_contract_compatibility():
    """Test that InMemoryStorage is compatible with SkillOptimizationStorage contract"""
    storage = InMemoryStorage()

    # This should work if contract is satisfied
    def use_storage(s: SkillOptimizationStorage) -> None:
        # Just check it's accepted by type checker
        pass

    use_storage(storage)  # Should not raise type error


@pytest.mark.asyncio
async def test_storage_protocol_methods_work():
    """Integration test: verify Protocol methods work end-to-end"""
    from datetime import datetime

    from myrm_agent_harness.agent.skills.optimization import (
        OptimizationResult,
        OptimizationStatus,
        SkillQualityScore,
        SkillType,
    )
    from myrm_agent_harness.agent.skills.optimization.types import SecurityValidationResult

    storage = InMemoryStorage()

    # Create test data
    score = SkillQualityScore(0.8, 0.7, 0.6, 0.9, 0.5)
    result = OptimizationResult(
        skill_id="test-skill",
        skill_type=SkillType.USER,
        baseline_score=score,
        optimized_content="# Test",
        security_validation=SecurityValidationResult(passed=True, issues=[]),
        status=OptimizationStatus.COMPLETED,
        started_at=datetime.now(),
        completed_at=datetime.now(),
    )

    # Use Protocol methods
    await storage.save_optimization_record(result)
    retrieved = await storage.get_optimization_record("test-skill")

    assert retrieved is not None
    assert retrieved.skill_id == "test-skill"

    # Quality snapshot
    await storage.save_quality_snapshot("test-skill", score)
    latest_quality = await storage.get_latest_quality("test-skill")

    assert latest_quality is not None
    assert latest_quality.success_rate == 0.8

    # SkillVersion lifecycle
    v1 = await storage.save_skill_version(
        skill_id="test-skill", version=1, content="V1 content", quality_score=score, created_by="llm"
    )
    assert v1.version == 1
    assert v1.is_active is False

    await storage.save_skill_version(
        skill_id="test-skill", version=2, content="V2 content", quality_score=score, created_by="manual"
    )

    versions = await storage.list_skill_versions("test-skill")
    assert len(versions) == 2
    assert versions[0].version == 2

    activated = await storage.activate_version("test-skill", 1)
    assert activated.is_active is True

    active = await storage.get_active_version("test-skill")
    assert active is not None
    assert active.version == 1

    deleted = await storage.delete_skill_versions("test-skill", keep_latest=1)
    assert deleted >= 0
