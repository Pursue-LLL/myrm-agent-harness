"""Tests for External CLI Subagent Adapter Bridge and Subscription Passthrough."""

import pytest
from myrm_agent_harness.agent.sub_agents.cli_passthrough import (
    BundleNotFoundError,
    CliPassthroughScheduler,
    CliProfileBundle,
    CliProfileBundleRegistry,
    CliSubagentType,
    CliTaskDelegationRequest,
    PrivacyDisclosureRequiredError,
    SensitivityLevel,
    SubscriptionStatus,
    WorkspaceEscalationForbiddenError,
)


@pytest.fixture
def registry() -> CliProfileBundleRegistry:
    return CliProfileBundleRegistry(default_workspace_root="/workspace/repo")


@pytest.fixture
def scheduler(registry: CliProfileBundleRegistry) -> CliPassthroughScheduler:
    return CliPassthroughScheduler(registry=registry)


def test_default_bundles_initialization(registry: CliProfileBundleRegistry) -> None:
    bundles = registry.list_bundles()
    assert len(bundles) >= 3
    bundle_ids = [b.bundle_id for b in bundles]
    assert "bundle-claude-code" in bundle_ids
    assert "bundle-codex-cli" in bundle_ids
    assert "bundle-cursor-cli" in bundle_ids

    claude = registry.get_bundle("bundle-claude-code")
    assert claude is not None
    assert claude.cli_type == CliSubagentType.CLAUDE_CODE
    assert claude.subscription_status == SubscriptionStatus.ACTIVE_PRO
    assert "--non-interactive" in claude.default_flags


def test_probe_environment(registry: CliProfileBundleRegistry) -> None:
    probe_results = registry.probe_environment()
    assert "bundle-claude-code" in probe_results
    assert "bundle-codex-cli" in probe_results
    assert "bundle-cursor-cli" in probe_results
    assert probe_results["bundle-claude-code"] is True


def test_custom_bundle_registration(registry: CliProfileBundleRegistry) -> None:
    custom_bundle = CliProfileBundle(
        bundle_id="bundle-custom-hermes",
        cli_type=CliSubagentType.GENERIC_CLI,
        display_name="Hermes CLI Runner",
        executable_name="hermes",
        subscription_status=SubscriptionStatus.FREE_TIER,
        allowed_workspace_root="/workspace/repo",
    )
    registry.register_bundle(custom_bundle)
    assert registry.get_bundle("bundle-custom-hermes") == custom_bundle


def test_privacy_disclosure_creation(scheduler: CliPassthroughScheduler) -> None:
    disclosure = scheduler.create_privacy_disclosure(
        cli_type=CliSubagentType.CLAUDE_CODE,
        context_summary="Refactoring vector index computation in src/math.py",
        sensitivity_level=SensitivityLevel.HIGH,
    )
    assert disclosure.cli_type == CliSubagentType.CLAUDE_CODE
    assert disclosure.vendor_name == "Anthropic PBC"
    assert "anthropic.com" in disclosure.data_handling_terms_url
    assert disclosure.user_acknowledged is False
    assert disclosure.sensitivity_level == SensitivityLevel.HIGH


def test_privacy_gate_unacknowledged_fails(scheduler: CliPassthroughScheduler) -> None:
    disclosure = scheduler.create_privacy_disclosure(
        cli_type=CliSubagentType.CODEX,
        context_summary="Review PR diff",
    )
    # user_acknowledged is False
    req = CliTaskDelegationRequest(
        task_id="task-001",
        bundle_id="bundle-codex-cli",
        instruction="Run automated code completion",
        workspace_path="/workspace/repo/src",
        disclosure=disclosure,
    )
    with pytest.raises(PrivacyDisclosureRequiredError, match="requires explicit acknowledgment"):
        scheduler.execute_delegated_task(req)


def test_workspace_confinement_violation_fails(scheduler: CliPassthroughScheduler) -> None:
    disclosure = scheduler.create_privacy_disclosure(
        cli_type=CliSubagentType.CLAUDE_CODE,
        context_summary="Test escape",
    )
    disclosure.user_acknowledged = True

    # Path traversal outside allowed workspace root /workspace/repo
    req = CliTaskDelegationRequest(
        task_id="task-002",
        bundle_id="bundle-claude-code",
        instruction="Inspect system logs",
        workspace_path="/etc/passwd",
        disclosure=disclosure,
    )
    with pytest.raises(WorkspaceEscalationForbiddenError, match="outside allowed root"):
        scheduler.execute_delegated_task(req)


def test_successful_headless_execution_and_accounting(
    scheduler: CliPassthroughScheduler,
) -> None:
    disclosure = scheduler.create_privacy_disclosure(
        cli_type=CliSubagentType.CURSOR_CLI,
        context_summary="Neon AVX SIMD Porting",
        sensitivity_level=SensitivityLevel.LOW,
    )
    disclosure.user_acknowledged = True

    req = CliTaskDelegationRequest(
        task_id="task-003",
        bundle_id="bundle-cursor-cli",
        instruction="Optimize SIMD dot product loop",
        workspace_path="/workspace/repo/subproject",
        disclosure=disclosure,
        context_files=["subproject/simd.c", "subproject/simd.h"],
    )

    result = scheduler.execute_delegated_task(req)
    assert result.task_id == "task-003"
    assert result.exit_code == 0
    assert "--- a/subproject/simd.c" in result.diff_output
    assert result.tokens_saved_estimate >= 120
    assert len(result.tamper_proof_audit_hash) == 64
    assert result.egress_accounting_id.startswith("egress-")

    # Verify audit record
    audit_records = scheduler.list_audit_records()
    assert len(audit_records) == 1
    assert audit_records[0].tamper_proof_audit_hash == result.tamper_proof_audit_hash

    # Teardown clear
    scheduler.clear_audit_records()
    assert len(scheduler.list_audit_records()) == 0


def test_bundle_not_found_fails(scheduler: CliPassthroughScheduler) -> None:
    disclosure = scheduler.create_privacy_disclosure(
        cli_type=CliSubagentType.GENERIC_CLI,
        context_summary="Missing bundle",
    )
    disclosure.user_acknowledged = True

    req = CliTaskDelegationRequest(
        task_id="task-004",
        bundle_id="bundle-nonexistent",
        instruction="Do work",
        workspace_path="/workspace/repo",
        disclosure=disclosure,
    )
    with pytest.raises(BundleNotFoundError, match="not registered"):
        scheduler.execute_delegated_task(req)
