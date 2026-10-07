# [POS]: tests/unit/toolkits/memory/test_rule_cascade_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.rule_cascade
# [OUTPUT]: Unit test suite for FiveDimPreFilteredEvidenceMemoryAndDeterministicRuleCascadeSuite (Item 99)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.rule_cascade import (
    DeterministicRuleCascadeLoader,
    DeterministicRuleEntry,
    EvidencePermissionLevel,
    EvidenceScopeKind,
    EvidenceSourceKind,
    FiveDimEvidenceMetadata,
    FiveDimFilterSpec,
    FiveDimPreFilterEngine,
    TimeDecayCalculator,
)


def test_deterministic_rule_cascade_path_inheritance_and_override() -> None:
    """Validate hierarchical directory inheritance and deeper leaf rule overrides."""
    loader = DeterministicRuleCascadeLoader()

    # Level 1: Global root rule
    r_root = DeterministicRuleEntry(
        rule_id="rule-global-lint",
        title="Linting Standard",
        rule_content="Base PEP-8 guidelines apply.",
        metadata=FiveDimEvidenceMetadata(
            scope=EvidenceScopeKind.GLOBAL,
            scope_path="/",
            source=EvidenceSourceKind.AGENT_INFERRED,
            source_authority=0.4,
        ),
    )

    # Level 2: Workspace rule
    r_ws = DeterministicRuleEntry(
        rule_id="rule-ws-test",
        title="Testing Framework",
        rule_content="Run all test suites with pytest.",
        metadata=FiveDimEvidenceMetadata(
            scope=EvidenceScopeKind.WORKSPACE,
            scope_path="/workspace",
            source=EvidenceSourceKind.TOOL_VERIFIED,
            source_authority=0.8,
        ),
    )

    # Level 3: Billing package rule overriding root linting standard
    r_billing_lint = DeterministicRuleEntry(
        rule_id="rule-billing-strict-lint",
        title="Linting Standard",
        rule_content="Strict zero-warning Ruff check enforced for billing.",
        metadata=FiveDimEvidenceMetadata(
            scope=EvidenceScopeKind.DIRECTORY,
            scope_path="/workspace/packages/billing",
            source=EvidenceSourceKind.USER_EXPLICIT,
            source_authority=1.0,
        ),
    )

    # Level 3: Billing security rule
    r_billing_sec = DeterministicRuleEntry(
        rule_id="rule-billing-pci",
        title="PCI Compliance",
        rule_content="Never log full credit card PAN or CVV.",
        metadata=FiveDimEvidenceMetadata(
            scope=EvidenceScopeKind.DIRECTORY,
            scope_path="/workspace/packages/billing",
            source=EvidenceSourceKind.USER_EXPLICIT,
            source_authority=1.0,
            permission=EvidencePermissionLevel.CONFIDENTIAL_ADMIN,
        ),
    )

    loader.register_rules([r_root, r_ws, r_billing_lint, r_billing_sec])

    # Resolve cascade for a nested billing service
    result = loader.resolve_cascade("/workspace/packages/billing/services")

    assert result.target_path == "/workspace/packages/billing/services"
    # Expected 3 rules:
    # 1. "Linting Standard" (overridden by billing package)
    # 2. "Testing Framework" (inherited from /workspace)
    # 3. "PCI Compliance" (inherited from /workspace/packages/billing)
    assert result.effective_rules_count == 3

    by_title = {r.title: r for r in result.inherited_rules}
    assert "Testing Framework" in by_title
    assert "PCI Compliance" in by_title
    assert "Linting Standard" in by_title

    # Confirm that deeper leaf rule won over root rule
    assert by_title["Linting Standard"].rule_id == "rule-billing-strict-lint"
    assert (
        by_title["Linting Standard"].rule_content
        == "Strict zero-warning Ruff check enforced for billing."
    )

    # Check sources breakdown
    assert result.sources_breakdown.get("user_explicit") == 2
    assert result.sources_breakdown.get("tool_verified") == 1


def test_time_decay_calculator_exponential_half_life() -> None:
    """Verify mathematical properties of exponential half-life decay calculation."""
    decay = TimeDecayCalculator()
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

    # Day 0: no decay
    factor_0 = decay.compute_decay_factor(elapsed_days=0.0, half_life_days=30.0)
    assert factor_0 == 1.0

    # Day 30: exactly 1 half-life elapsed -> factor should be 0.5
    factor_30 = decay.compute_decay_factor(elapsed_days=30.0, half_life_days=30.0)
    assert pytest.approx(factor_30, rel=1e-4) == 0.5

    # Day 60: exactly 2 half-lives elapsed -> factor should be 0.25
    factor_60 = decay.compute_decay_factor(elapsed_days=60.0, half_life_days=30.0)
    assert pytest.approx(factor_60, rel=1e-4) == 0.25

    # Test effective confidence decay
    created_iso = (now - timedelta(days=30)).isoformat()
    meta = FiveDimEvidenceMetadata(
        scope=EvidenceScopeKind.WORKSPACE,
        scope_path="/workspace",
        source=EvidenceSourceKind.USER_EXPLICIT,
        source_authority=1.0,
        created_at=created_iso,
        half_life_days=30.0,
        confidence=0.8,
    )

    effective_conf = decay.compute_effective_confidence(meta, now=now)
    assert pytest.approx(effective_conf, rel=1e-4) == 0.4  # 0.8 * 0.5

    assert not decay.is_expired(meta, threshold=0.3, now=now)
    assert decay.is_expired(meta, threshold=0.5, now=now)


def test_five_dim_pre_filter_engine_physical_isolation() -> None:
    """Validate 5-dimensional pre-filtering blocks unauthorized and out-of-scope facts."""
    decay = TimeDecayCalculator()
    engine = FiveDimPreFilterEngine(decay_calculator=decay)
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

    candidates = [
        # Candidate 1: Valid workspace rule
        DeterministicRuleEntry(
            rule_id="valid-01",
            title="Public WS Rule",
            rule_content="General rule",
            metadata=FiveDimEvidenceMetadata(
                scope=EvidenceScopeKind.WORKSPACE,
                scope_path="/workspace/app",
                source=EvidenceSourceKind.USER_EXPLICIT,
                source_authority=1.0,
                created_at=now.isoformat(),
                confidence=1.0,
                permission=EvidencePermissionLevel.WORKSPACE_INTERNAL,
            ),
        ),
        # Candidate 2: Confidential admin rule (should be blocked for regular query)
        DeterministicRuleEntry(
            rule_id="blocked-perm",
            title="Admin Key Rule",
            rule_content="Top secret credential pattern",
            metadata=FiveDimEvidenceMetadata(
                scope=EvidenceScopeKind.WORKSPACE,
                scope_path="/workspace/app",
                source=EvidenceSourceKind.USER_EXPLICIT,
                source_authority=1.0,
                created_at=now.isoformat(),
                confidence=1.0,
                permission=EvidencePermissionLevel.CONFIDENTIAL_ADMIN,
            ),
        ),
        # Candidate 3: Low authority inferred noise (should be blocked by min_authority)
        DeterministicRuleEntry(
            rule_id="blocked-auth",
            title="Uncertain Assumption",
            rule_content="Maybe port 8080",
            metadata=FiveDimEvidenceMetadata(
                scope=EvidenceScopeKind.WORKSPACE,
                scope_path="/workspace/app",
                source=EvidenceSourceKind.AGENT_INFERRED,
                source_authority=0.4,
                created_at=now.isoformat(),
                confidence=1.0,
                permission=EvidencePermissionLevel.PUBLIC,
            ),
        ),
        # Candidate 4: Unrelated directory path
        DeterministicRuleEntry(
            rule_id="blocked-scope",
            title="Other Project Rule",
            rule_content="Ignore this",
            metadata=FiveDimEvidenceMetadata(
                scope=EvidenceScopeKind.WORKSPACE,
                scope_path="/other_project/billing",
                source=EvidenceSourceKind.USER_EXPLICIT,
                source_authority=1.0,
                created_at=now.isoformat(),
                confidence=1.0,
                permission=EvidencePermissionLevel.PUBLIC,
            ),
        ),
    ]

    # Query spec: required permission is WORKSPACE_INTERNAL (cannot access CONFIDENTIAL_ADMIN)
    spec = FiveDimFilterSpec(
        scope_path_prefix="/workspace",
        min_authority=0.8,
        min_confidence=0.5,
        required_permission=EvidencePermissionLevel.WORKSPACE_INTERNAL,
    )

    filtered = engine.filter_evidence(candidates, spec, now=now)

    assert filtered.total_evaluated == 4
    assert filtered.passed_count == 1
    assert filtered.items[0].rule_id == "valid-01"

    # Rejection reasons audit check
    assert filtered.rejection_reasons["permission_denied"] == 1
    assert filtered.rejection_reasons["authority_insufficient"] == 1
    assert filtered.rejection_reasons["path_prefix_mismatch"] == 1
