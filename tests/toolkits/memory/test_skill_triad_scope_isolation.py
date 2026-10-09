"""Comprehensive unit tests for memory skill triad and physical scope isolation suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.skill_triad import (
    DegradedSeverity,
    DegradedStateObserver,
    IntegrationPipelineValidator,
    IntegrationSeams,
    MachineEnvelopeFormatter,
    MemorySkillTriadFacade,
    ScopeCoordinates,
    ScopePhysicalPartitionEngine,
    SurveyFinding,
    get_memory_skill_triad_facade,
)


def test_scope_hash_collision_resistance() -> None:
    """Verifies length-prefixed sorted keys eliminate boundary collisions."""
    # (user='a', agent='bc') vs (user='ab', agent='c')
    coord1 = ScopeCoordinates(
        tenant_id="t1", workspace_id="w1", agent_id="bc", session_id="a"
    )
    coord2 = ScopeCoordinates(
        tenant_id="t1", workspace_id="w1", agent_id="c", session_id="ab"
    )

    hash1 = ScopePhysicalPartitionEngine.compute_namespace_hash(coord1)
    hash2 = ScopePhysicalPartitionEngine.compute_namespace_hash(coord2)

    assert hash1 != hash2, "Boundary tokens must never collide across dimension lengths"
    assert len(hash1) == 32
    assert len(hash2) == 32


def test_scope_physical_directory_resolution(tmp_path: Path) -> None:
    """Tests resolution of isolated filesystem directory and dedicated SQLite path."""
    engine = ScopePhysicalPartitionEngine(base_storage_dir=tmp_path)
    coords = ScopeCoordinates(
        tenant_id="enterprise_alpha",
        workspace_id="billing_app",
        agent_id="reconciliation_agent",
        session_id="session_001",
    )

    partition = engine.resolve_partition(coords, auto_create_dir=True)

    assert partition.is_isolated is True
    assert Path(partition.partition_dir).exists()
    assert Path(partition.partition_dir).is_dir()
    assert partition.sqlite_path.endswith("memory.sqlite")

    active_partitions = engine.list_active_partitions()
    assert partition.namespace_hash in active_partitions


def test_scope_atomic_directory_deletion(tmp_path: Path) -> None:
    """Tests that tenant or session purge is a pure, atomic directory removal."""
    engine = ScopePhysicalPartitionEngine(base_storage_dir=tmp_path)
    coords = ScopeCoordinates(tenant_id="tenant_x", session_id="sess_temp")

    partition = engine.resolve_partition(coords, auto_create_dir=True)
    assert Path(partition.partition_dir).exists()

    # Create dummy file inside partition
    dummy_file = Path(partition.partition_dir) / "test_data.txt"
    dummy_file.write_text("sample content", encoding="utf-8")

    deleted = engine.delete_partition(coords)
    assert deleted is True
    assert not Path(partition.partition_dir).exists()
    assert partition.namespace_hash not in engine.list_active_partitions()


def test_provider_degradation_observation() -> None:
    """Tests visible degradation when external provider is unavailable."""
    observer = DegradedStateObserver()

    # 1. Nominal case: Built-in local providers
    nominal_report = observer.assess_providers(
        {"embedder": "builtin", "llm": "deterministic_rules"}
    )
    assert nominal_report.overall_status == DegradedSeverity.HEALTHY
    assert nominal_report.has_any_degradation is False

    # 2. Degraded case: Cloud vendor unavailable, fall back visibly
    degraded_report = observer.assess_providers(
        {"embedder": "cloud_openai", "vector_store": "remote_qdrant"}
    )
    assert degraded_report.overall_status == DegradedSeverity.DEGRADED_LEXICAL_FALLBACK
    assert degraded_report.has_any_degradation is True

    embed_info = next(p for p in degraded_report.providers if p.provider_type == "embedder")
    assert embed_info.is_degraded is True
    assert embed_info.active_vendor == "builtin_tfidf_128d"
    assert "unavailable" in embed_info.degradation_reason


def test_provider_strict_mode_raises() -> None:
    """Tests that strict_providers=True raises RuntimeError instead of silent degradation."""
    observer = DegradedStateObserver()

    with pytest.raises(RuntimeError, match="Strict provider enforcement failed"):
        observer.assess_providers({"embedder": "cloud_cohere"}, strict_mode=True)


def test_cli_machine_envelope_success_and_error() -> None:
    """Tests CLI machine envelope formatting for successes and errors."""
    coords = ScopeCoordinates(tenant_id="org_dev", session_id="cli_sess")

    # Success envelope
    success_env = MachineEnvelopeFormatter.wrap_success(
        command="search",
        start_time_s=100.0,
        scope=coords,
        payload={"query": "dark mode", "hit_count": "2"},
        agent_mode=True,
    )
    assert success_env.is_success is True
    assert success_env.exit_code == 0
    assert success_env.auto_confirmed is True
    assert success_env.payload["hit_count"] == "2"

    # Error envelope with mapped code and exit_code
    error_env = MachineEnvelopeFormatter.wrap_error(
        command="delete",
        start_time_s=100.0,
        scope=coords,
        error_type="SCOPE_EMPTY",
        error_message="Scope required for delete operation",
        agent_mode=True,
    )
    assert error_env.is_success is False
    assert error_env.exit_code == 4
    assert error_env.error_code == "MEM_ERR_SCOPE_REQUIRED_089"
    assert error_env.auto_confirmed is True


def test_integration_pipeline_survey_validation() -> None:
    """Tests validating 4-question pre-integration repository survey findings."""
    valid_survey = SurveyFinding(
        message_assembly_site="app/chat/prompt_builder.py:45",
        identity_binding="session_context.user_id",
        installed_provider="openai package available",
        write_hook_seam="app/chat/runner.py:120 post-turn callback",
        is_ready_for_wiring=True,
    )
    is_valid, issues = IntegrationPipelineValidator.validate_survey(valid_survey)
    assert is_valid is True
    assert len(issues) == 0

    invalid_survey = SurveyFinding(
        message_assembly_site="",
        identity_binding="",
        installed_provider="",
        write_hook_seam="",
    )
    is_invalid, missing = IntegrationPipelineValidator.validate_survey(invalid_survey)
    assert is_invalid is False
    assert len(missing) == 4


def test_integration_seams_and_roundtrip_probe(tmp_path: Path) -> None:
    """Tests verifying read/write seams and executing roundtrip probe."""
    seams = IntegrationSeams(
        read_seam_configured=True,
        write_seam_configured=True,
        token_budget=400,
        roundtrip_test_passed=True,
    )
    ok, msg = IntegrationPipelineValidator.verify_seams(seams)
    assert ok is True
    assert "successfully verified" in msg

    # Probe test
    probe_ok = IntegrationPipelineValidator.execute_roundtrip_probe(
        probe_dir=tmp_path / "probe_store",
        stored_preference="User prefers dark mode and vim editor",
        query_text="what is vim mode preference",
    )
    assert probe_ok is True


def test_memory_skill_triad_facade_and_singleton(tmp_path: Path) -> None:
    """Tests MemorySkillTriadFacade unified operations and singleton accessor."""
    facade = MemorySkillTriadFacade(base_storage_dir=tmp_path)
    coords = ScopeCoordinates(tenant_id="facade_t", session_id="facade_s")

    partition = facade.resolve_scope(coords)
    assert partition.namespace_hash is not None

    report = facade.assess_providers({"llm": "deterministic_rules"})
    assert report.overall_status == DegradedSeverity.HEALTHY

    env = facade.wrap_cli_success(
        command="test_cmd",
        start_time_s=10.0,
        scope=coords,
        payload={"res": "ok"},
    )
    assert env.is_success is True

    singleton = get_memory_skill_triad_facade()
    assert isinstance(singleton, MemorySkillTriadFacade)
