"""Tests for Universal Agent State Capsule & Cross-Device Migration Engine."""

import json

import pytest

from myrm_agent_harness.runtime.context.agent_state_capsule import (
    AgentProfileCapsule,
    CapsuleIntegrityError,
    CapsuleMergeStrategy,
    CapsuleMigrationResolver,
    CapsuleSerializationEngine,
    MemoryCapsuleEntry,
    SessionCheckpointCapsuleEntry,
    SkillCapsuleEntry,
)


def _make_sample_capsule():
    profile = AgentProfileCapsule(
        agent_id="agent-coder-99",
        name="Senior Fullstack Architect",
        description="Autonomous fullstack agent",
        system_prompt="You are a senior staff engineer.",
        model_provider="openai",
        model_name="gpt-4o",
        temperature=0.2,
        max_tokens=8192,
        metadata={"version": "2.4"},
    )
    skills = (
        SkillCapsuleEntry(
            skill_id="sk-1",
            name="github_ops",
            description="GitHub integration",
            code_or_config="def sync(): pass",
            mcp_server_ref="github_mcp",
            enabled=True,
        ),
    )
    memories = (
        MemoryCapsuleEntry(
            memory_id="mem-1",
            memory_type="episodic",
            content="Always use bun instead of npm in frontend workspace.",
            importance=0.9,
            tags=("frontend", "bun"),
            created_at_utc="2026-10-06T12:00:00Z",
            embedding_vector=(0.12, 0.34, -0.56),
        ),
    )
    checkpoints = (
        SessionCheckpointCapsuleEntry(
            session_id="sess-epoch-1",
            epoch_index=1,
            summary_text="Completed initial scaffolding",
            created_at_utc="2026-10-06T12:30:00Z",
        ),
    )
    return CapsuleSerializationEngine.create_capsule(
        capsule_id="cap-uuid-001",
        created_at_utc="2026-10-06T12:00:00Z",
        source_host="macbook-m3-pro",
        profile=profile,
        skills=skills,
        memories=memories,
        checkpoints=checkpoints,
    )


def test_capsule_create_and_serialize_integrity():
    capsule = _make_sample_capsule()
    assert capsule.header.checksum_sha256 != ""
    assert capsule.profile.agent_id == "agent-coder-99"

    json_str = CapsuleSerializationEngine.to_json(capsule)
    restored = CapsuleSerializationEngine.from_json(json_str, verify_integrity=True)

    assert restored.header.capsule_id == "cap-uuid-001"
    assert restored.profile.model_name == "gpt-4o"
    assert len(restored.skills) == 1
    assert restored.skills[0].name == "github_ops"
    assert len(restored.memories) == 1
    assert restored.memories[0].embedding_vector == (0.12, 0.34, -0.56)
    assert len(restored.checkpoints) == 1


def test_capsule_tamper_detection():
    capsule = _make_sample_capsule()
    json_str = CapsuleSerializationEngine.to_json(capsule)

    raw_dict = json.loads(json_str)
    # Tamper with profile prompt without updating checksum
    raw_dict["profile"]["system_prompt"] = "Tampered prompt"
    tampered_json = json.dumps(raw_dict)

    with pytest.raises(CapsuleIntegrityError) as exc_info:
        CapsuleSerializationEngine.from_json(tampered_json, verify_integrity=True)
    assert "Integrity checksum mismatch" in str(exc_info.value)


def test_environment_diagnostics():
    capsule = _make_sample_capsule()

    # Missing openai key and missing github_mcp tool
    diag = CapsuleMigrationResolver.diagnose_environment(
        capsule,
        available_env_vars=set(),
        available_tools=set(),
    )
    assert not diag.is_ready
    assert "OPENAI_API_KEY" in diag.missing_env_vars
    assert "github_mcp" in diag.missing_tools

    # Ready when dependencies satisfied
    ready_diag = CapsuleMigrationResolver.diagnose_environment(
        capsule,
        available_env_vars={"OPENAI_API_KEY"},
        available_tools={"github_mcp"},
    )
    assert ready_diag.is_ready
    assert len(ready_diag.warnings) == 0


def test_migration_strategy_create_new():
    capsule = _make_sample_capsule()
    existing_profile = AgentProfileCapsule(
        agent_id="agent-coder-99",
        name="Existing Architect",
        description="Local agent",
        system_prompt="Old prompt",
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        temperature=0.5,
        max_tokens=4096,
        metadata={},
    )

    resolved = CapsuleMigrationResolver.resolve_migration(
        capsule,
        existing_profile=existing_profile,
        existing_skills=(),
        existing_memories=(),
        existing_checkpoints=(),
        strategy=CapsuleMergeStrategy.CREATE_NEW,
        id_generator=lambda base: f"{base}_cloned",
    )

    assert resolved.strategy_applied == CapsuleMergeStrategy.CREATE_NEW
    assert resolved.profile.agent_id == "agent-coder-99_cloned"
    assert "(Imported)" in resolved.profile.name
    assert resolved.skills[0].skill_id == "sk-1_cloned"
    assert resolved.memories[0].memory_id == "mem-1_cloned"


def test_migration_strategy_overwrite():
    capsule = _make_sample_capsule()
    existing_profile = AgentProfileCapsule(
        agent_id="agent-coder-99",
        name="Outdated Profile",
        description="Old",
        system_prompt="Old prompt",
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        temperature=0.5,
        max_tokens=4096,
        metadata={},
    )

    resolved = CapsuleMigrationResolver.resolve_migration(
        capsule,
        existing_profile=existing_profile,
        existing_skills=(),
        existing_memories=(),
        existing_checkpoints=(),
        strategy=CapsuleMergeStrategy.OVERWRITE,
    )

    assert resolved.strategy_applied == CapsuleMergeStrategy.OVERWRITE
    assert resolved.profile.model_name == "gpt-4o"
    assert resolved.profile.name == "Senior Fullstack Architect"


def test_migration_strategy_incremental_merge():
    capsule = _make_sample_capsule()
    existing_profile = AgentProfileCapsule(
        agent_id="agent-coder-99",
        name="Local Mainstay",
        description="Local agent",
        system_prompt="Local prompt",
        model_provider="openai",
        model_name="gpt-4o",
        temperature=0.2,
        max_tokens=8192,
        metadata={},
    )
    existing_skills = (
        SkillCapsuleEntry(
            skill_id="sk-local-1",
            name="github_ops",  # Name collision: should preserve local version
            description="Local GitHub integration",
            code_or_config="def local_sync(): pass",
            mcp_server_ref="github_mcp",
            enabled=True,
        ),
    )
    existing_memories = (
        MemoryCapsuleEntry(
            memory_id="mem-dup",
            memory_type="episodic",
            content="Always use bun instead of npm in frontend workspace.",  # Duplicate content
            importance=0.9,
            tags=("frontend",),
            created_at_utc="2026-10-06T10:00:00Z",
        ),
    )
    existing_checkpoints = (
        SessionCheckpointCapsuleEntry(
            session_id="sess-epoch-0",
            epoch_index=0,
            summary_text="Project initialized",
            created_at_utc="2026-10-06T09:00:00Z",
        ),
    )

    resolved = CapsuleMigrationResolver.resolve_migration(
        capsule,
        existing_profile=existing_profile,
        existing_skills=existing_skills,
        existing_memories=existing_memories,
        existing_checkpoints=existing_checkpoints,
        strategy=CapsuleMergeStrategy.INCREMENTAL_MERGE,
    )

    assert resolved.strategy_applied == CapsuleMergeStrategy.INCREMENTAL_MERGE
    # Preserved local duplicate skill
    assert len(resolved.skills) == 1
    assert resolved.skills[0].code_or_config == "def local_sync(): pass"
    # Deduplicated identical content memory
    assert len(resolved.memories) == 1
    assert resolved.memories[0].memory_id == "mem-dup"
    # Combined and ordered checkpoints
    assert len(resolved.checkpoints) == 2
    assert resolved.checkpoints[0].epoch_index == 0
    assert resolved.checkpoints[1].epoch_index == 1
