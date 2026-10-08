"""Unit tests for Scoped Time-Bounded Action Grant Registry and Trust Budget Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.action_grants import (
    ActionGrantRegistry,
    TrustBudgetEngine,
)


def test_grant_creation_and_successful_evaluation() -> None:
    """Test standard 4D grant creation and matched evaluation."""
    registry = ActionGrantRegistry()
    grant = registry.create_grant(
        agent_id="agent-alice",
        service="feishu",
        action="send",
        transaction="chat_123",
        ttl_seconds=300,
        max_uses=2,
    )

    assert grant.grant_id.startswith("grant_")
    assert grant.used_count == 0

    # 1. First evaluation succeeds and increments used_count
    eval_res1, updated1 = registry.evaluate_action(
        agent_id="agent-alice",
        service="feishu",
        action="send",
        transaction="chat_123",
    )
    assert eval_res1.is_granted is True
    assert eval_res1.status == "granted"
    assert updated1 is not None
    assert updated1.used_count == 1

    # 2. Second evaluation succeeds and hits max_uses limit
    eval_res2, updated2 = registry.evaluate_action(
        agent_id="agent-alice",
        service="feishu",
        action="send",
        transaction="chat_123",
    )
    assert eval_res2.is_granted is True
    assert updated2 is not None
    assert updated2.used_count == 2

    # 3. Third evaluation is rejected due to quota exhaustion
    eval_res3, _ = registry.evaluate_action(
        agent_id="agent-alice",
        service="feishu",
        action="send",
        transaction="chat_123",
    )
    assert eval_res3.is_granted is False
    assert eval_res3.status == "not_found"


def test_agent_isolation_prevents_privilege_impersonation() -> None:
    """Test that a grant issued to Agent A cannot be consumed or matched by Agent B."""
    registry = ActionGrantRegistry()
    registry.create_grant(
        agent_id="agent-finance",
        service="stripe",
        action="charge",
        transaction="inv_999",
        ttl_seconds=600,
    )

    # Agent Bob tries to use Agent Finance's grant
    eval_res, _ = registry.evaluate_action(
        agent_id="agent-bob",
        service="stripe",
        action="charge",
        transaction="inv_999",
    )
    assert eval_res.is_granted is False
    assert eval_res.status == "not_found"


def test_transaction_wildcard_matching() -> None:
    """Test wildcard transaction matching allows multiple distinct transactions within scope."""
    registry = ActionGrantRegistry()
    registry.create_grant(
        agent_id="agent-coder",
        service="github",
        action="read",
        transaction="*",
        ttl_seconds=600,
    )

    res_pr1, _ = registry.evaluate_action(
        agent_id="agent-coder",
        service="github",
        action="read",
        transaction="pr_101",
    )
    res_pr2, _ = registry.evaluate_action(
        agent_id="agent-coder",
        service="github",
        action="read",
        transaction="pr_202",
    )
    assert res_pr1.is_granted is True
    assert res_pr2.is_granted is True


def test_monotonic_revocation_and_cascade_reclaim() -> None:
    """Test single grant revocation and cascaded connector/service reclamation."""
    registry = ActionGrantRegistry()
    g1 = registry.create_grant("agent-1", "slack", "post", "chan_a", 300)
    g2 = registry.create_grant("agent-1", "slack", "post", "chan_b", 300)
    g3 = registry.create_grant("agent-1", "github", "merge", "pr_1", 300)
    assert g2.grant_id != g1.grant_id
    assert g3.service == "github"

    # Revoke single grant g1
    assert registry.revoke_grant(g1.grant_id, "User clicked revoke") is True
    assert registry.revoke_grant(g1.grant_id) is False  # Already revoked

    res_g1, _ = registry.evaluate_action("agent-1", "slack", "post", "chan_a")
    assert res_g1.is_granted is False

    # Cascade revoke slack connector
    reclaimed = registry.cascade_reclaim_by_service("slack", "Slack OAuth disconnected")
    assert reclaimed == 1  # g2 was active, g1 was already revoked

    res_g2, _ = registry.evaluate_action("agent-1", "slack", "post", "chan_b")
    assert res_g2.is_granted is False

    # g3 (github) is still active
    res_g3, _ = registry.evaluate_action("agent-1", "github", "merge", "pr_1")
    assert res_g3.is_granted is True


def test_trust_budget_accumulation_and_demotion() -> None:
    """Test trust budget accumulation and deterministic collapse upon demotion."""
    engine = TrustBudgetEngine(default_suggestion_threshold=3)

    # 1. Consecutive approvals increment trust
    b1 = engine.record_approval("agent-ops", "database", "query")
    assert b1.consecutive_approvals == 1
    assert engine.should_suggest_grant("agent-ops", "database", "query") is False

    engine.record_approval("agent-ops", "database", "query")
    b3 = engine.record_approval("agent-ops", "database", "query")
    assert b3.consecutive_approvals == 3
    assert engine.should_suggest_grant("agent-ops", "database", "query") is True

    # 2. User demotion immediately zeroes budget and locks to Ask
    demoted = engine.record_demotion(
        "agent-ops", "database", "query", reason="User disapproved query plan"
    )
    assert demoted.consecutive_approvals == 0
    assert demoted.is_locked_to_ask is True
    assert engine.should_suggest_grant("agent-ops", "database", "query") is False

    # 3. Unlock ask clears lock
    unlocked = engine.unlock_ask("agent-ops", "database", "query")
    assert unlocked.is_locked_to_ask is False
    assert unlocked.consecutive_approvals == 0
