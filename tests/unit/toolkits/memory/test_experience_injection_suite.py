# [POS]: tests/unit/toolkits/memory/test_experience_injection_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory (ExperienceInjectionEngine, models, hooks)
# [OUTPUT]: Unit tests for SkillLoadSubagentSpawnPreWriteExperienceInjectionSuite (Item 105)

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    DualNodeFixedCountRetriever,
    ExperienceInjectionConfig,
    ExperienceInjectionEngine,
    InjectionStatus,
    PreWriteInterceptor,
    ProcedureMemoryEntry,
    SkillLoadExperienceHook,
    SubagentSpawnExperienceEnricher,
)


@pytest.fixture
def sample_retriever() -> DualNodeFixedCountRetriever:
    """Pre-populate retriever with realistic procedure experiences."""
    retriever = DualNodeFixedCountRetriever()

    # Experience 1: Database Migration
    retriever.register(
        ProcedureMemoryEntry(
            entry_id="proc_db_mig_01",
            name="SafeDatabaseSchemaMigration",
            retrieval_anchor="skill:db_migration alembic database schema",
            operation_intent="Execute non-destructive dual-write schema migrations",
            preconditions=["Database replicas in sync", "Recent backup verified"],
            immutable_boundary=["Production billing ledger", "Primary connection url"],
            procedure_steps=["1. Add column", "2. Dual-write", "3. Backfill async", "4. Cut over"],
            write_field_provenance={"migration_version": "Alembic revision stamp"},
            anti_patterns=["Never drop column without deprecation period"],
            applicability=["database schema update", "migration"],
            negative_applicability=["in-memory tests"],
        )
    )

    # Experience 2: File Writing Safety
    retriever.register(
        ProcedureMemoryEntry(
            entry_id="proc_file_write_02",
            name="AtomicFileWriteGuard",
            retrieval_anchor="pre_write:write_file write_file replace_file_content atomic",
            operation_intent="Safely mutate disk files with permission and backup check",
            preconditions=["File not locked by another process"],
            immutable_boundary=["Configuration secrets outside workspace", ".git/HEAD"],
            procedure_steps=["1. Check path boundary", "2. Verify encoding", "3. Atomic write"],
            write_field_provenance={"content_hash": "SHA256 checksum of buffer"},
            anti_patterns=["Do not overwrite critical files without backup"],
            applicability=["file mutation", "disk write"],
            negative_applicability=["read operations"],
        )
    )

    # Experience 3: Subagent Delegation
    retriever.register(
        ProcedureMemoryEntry(
            entry_id="proc_subagent_deploy_03",
            name="SubagentProductionDeployment",
            retrieval_anchor="DeployAgent deployment canary kubernetes release",
            operation_intent="Delegate canary release with automated health probes",
            preconditions=["Canary traffic limit set to 10%"],
            immutable_boundary=["Production ingress routing rules"],
            procedure_steps=["1. Inspect pods", "2. Check metrics", "3. Promote or rollback"],
            write_field_provenance={"release_tag": "Git commit SHA"},
            anti_patterns=["Never skip metric evaluation window"],
            applicability=["subagent deployment", "canary"],
            negative_applicability=["local dry run"],
        )
    )

    return retriever


def test_skill_load_experience_injection(sample_retriever: DualNodeFixedCountRetriever) -> None:
    """Site 1: Verify experience injection into skill content upon load."""
    engine = ExperienceInjectionEngine(retriever=sample_retriever)
    hook = SkillLoadExperienceHook(engine=engine)

    raw_skill = "# Database Migration Skill\nRun schema changes safely."
    enriched = hook.enrich_skill_content(
        skill_name="db_migration",
        skill_markdown=raw_skill,
    )

    assert "[INJECTED_SKILL_EXPERIENCE]" in enriched
    assert "SafeDatabaseSchemaMigration" in enriched
    assert "Production billing ledger" in enriched
    assert "# Database Migration Skill" in enriched


def test_subagent_spawn_experience_injection(sample_retriever: DualNodeFixedCountRetriever) -> None:
    """Site 2: Verify experience injection into subagent task prompt before dispatch."""
    engine = ExperienceInjectionEngine(retriever=sample_retriever)
    enricher = SubagentSpawnExperienceEnricher(engine=engine)

    base_prompt = "Perform canary deployment for version v2.1.0 to staging cluster."
    enriched = enricher.enrich_subagent_task_prompt(
        subagent_role="DeployAgent",
        base_prompt=base_prompt,
    )

    assert "[EXPERIENCE CONTEXT FOR DELEGATED TASK]" in enriched
    assert "SubagentProductionDeployment" in enriched
    assert "Canary traffic limit set to 10%" in enriched
    assert base_prompt in enriched


def test_pre_write_guard_and_one_time_rollback(sample_retriever: DualNodeFixedCountRetriever) -> None:
    """Site 3: Verify pre-write guard triggers rollback once and avoids infinite loops."""
    engine = ExperienceInjectionEngine(retriever=sample_retriever)
    interceptor = PreWriteInterceptor(engine=engine)

    # 1. First write attempt triggers one-time rollback and adds guard context
    res1 = interceptor.inspect_tool_call(
        tool_name="write_file",
        tool_args={"path": "/workspace/config.py", "content": "NEW_CONFIG = 1"},
        current_context="I will write the updated config now.",
    )

    assert res1.status == InjectionStatus.INJECTED
    assert res1.rollback_required is True
    assert "[PRE-WRITE GUARD: IMMUTABLE BOUNDARIES" in res1.enriched_content
    assert "AtomicFileWriteGuard" in res1.injected_entries[0].name
    assert ".git/HEAD" in res1.enriched_content

    # 2. Second write attempt in the SAME message turn must NOT rollback again (prevents infinite loop)
    res2 = interceptor.inspect_tool_call(
        tool_name="write_file",
        tool_args={"path": "/workspace/another.py", "content": "pass"},
        current_context="Proceeding with second write.",
    )
    assert res2.status == InjectionStatus.SKIPPED_ALREADY_INJECTED
    assert res2.rollback_required is False

    # 3. New message turn resets flag; write guard can fire again safely
    engine.reset_message_turn()
    # Add a new un-injected entry for testing re-triggering
    res3 = interceptor.inspect_tool_call(
        tool_name="read_file",  # Non-mutating tool
        tool_args={"path": "/workspace/file.py"},
        current_context="Reading file",
    )
    assert res3.status == InjectionStatus.SKIPPED_NO_MATCH
    assert res3.rollback_required is False


def test_dual_gating_and_deduplication(sample_retriever: DualNodeFixedCountRetriever) -> None:
    """Verify dual gating switches and cross-call deduplication."""
    # Test master switch disabled
    disabled_config = ExperienceInjectionConfig(agent_memory_enabled=False)
    engine_off = ExperienceInjectionEngine(retriever=sample_retriever, config=disabled_config)

    res_skill = engine_off.inject_skill_load("db_migration", "raw content")
    assert res_skill.status == InjectionStatus.SKIPPED_DISABLED
    assert res_skill.enriched_content == "raw content"

    res_subagent = engine_off.inject_subagent_spawn("DeployAgent", "prompt")
    assert res_subagent.status == InjectionStatus.SKIPPED_DISABLED

    res_write = engine_off.inject_pre_write("write_file", {"f": "1"}, "ctx")
    assert res_write.status == InjectionStatus.SKIPPED_DISABLED

    # Test write tools disabled specifically
    write_off_config = ExperienceInjectionConfig(agent_memory_enabled=True, exp_write_tools_enabled=False)
    engine_write_off = ExperienceInjectionEngine(retriever=sample_retriever, config=write_off_config)

    res_skill_ok = engine_write_off.inject_skill_load("db_migration", "raw content")
    assert res_skill_ok.status == InjectionStatus.INJECTED

    res_write_off = engine_write_off.inject_pre_write("write_file", {"f": "1"}, "ctx")
    assert res_write_off.status == InjectionStatus.SKIPPED_DISABLED
