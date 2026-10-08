"""Unit tests for PreToolUse Hook Interceptor & API Key Precedence in myrm-agent-harness."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.pre_tool_use_interceptor import (
    ApiKeyPrecedenceDetector,
    HardGateActionVerdict,
    HardGateSecurityRejectionError,
    HardRuleCategory,
    PreToolUseHookInterceptor,
)


@pytest.fixture
def interceptor() -> PreToolUseHookInterceptor:
    return PreToolUseHookInterceptor()


def test_interceptor_blocks_protected_branch_push(
    interceptor: PreToolUseHookInterceptor,
) -> None:
    # Blocked
    res_main = interceptor.intercept("run_command", "git push origin main")
    assert res_main.verdict == HardGateActionVerdict.BLOCK
    assert res_main.rule_category == HardRuleCategory.PROTECTED_BRANCH_PUSH

    res_master = interceptor.intercept("run_command", "git push upstream master")
    assert res_master.verdict == HardGateActionVerdict.BLOCK

    # Allowed: non-protected feature branch
    res_feature = interceptor.intercept("run_command", "git push origin feature/new-login")
    assert res_feature.verdict == HardGateActionVerdict.ALLOW


def test_interceptor_blocks_destructive_rm(
    interceptor: PreToolUseHookInterceptor,
) -> None:
    # Blocked
    res_root = interceptor.intercept("run_command", "rm -rf /")
    assert res_root.verdict == HardGateActionVerdict.BLOCK
    assert res_root.rule_category == HardRuleCategory.DESTRUCTIVE_COMMAND

    res_home = interceptor.intercept("run_command", "rm -fr ~")
    assert res_home.verdict == HardGateActionVerdict.BLOCK

    # Allowed: normal project build folder deletion
    res_build = interceptor.intercept("run_command", "rm -rf ./dist/build")
    assert res_build.verdict == HardGateActionVerdict.ALLOW


def test_interceptor_blocks_production_env_mutation(
    interceptor: PreToolUseHookInterceptor,
) -> None:
    # Blocked overwrite
    res_env = interceptor.intercept("run_command", "echo 'API_KEY=123' > .env.prod")
    assert res_env.verdict == HardGateActionVerdict.BLOCK
    assert res_env.rule_category == HardRuleCategory.PRODUCTION_ENV_MUTATION

    # Allowed: safe read
    res_read = interceptor.intercept("run_command", "cat .env.example")
    assert res_read.verdict == HardGateActionVerdict.ALLOW


def test_interceptor_blocks_database_drop(
    interceptor: PreToolUseHookInterceptor,
) -> None:
    # Blocked drop
    res_db = interceptor.intercept("run_command", "DROP DATABASE production_db;")
    assert res_db.verdict == HardGateActionVerdict.BLOCK
    assert res_db.rule_category == HardRuleCategory.DATABASE_DROP

    # Allowed query
    res_query = interceptor.intercept("run_command", "SELECT * FROM users WHERE active=1;")
    assert res_query.verdict == HardGateActionVerdict.ALLOW


def test_interceptor_raise_on_block(
    interceptor: PreToolUseHookInterceptor,
) -> None:
    with pytest.raises(HardGateSecurityRejectionError) as exc_info:
        interceptor.intercept(
            "run_command",
            "git push origin main",
            raise_on_block=True,
        )
    assert exc_info.value.category == HardRuleCategory.PROTECTED_BRANCH_PUSH


def test_api_key_precedence_detector() -> None:
    # Conflict case: subscription active, but ambient env var exists
    fake_env = {"ANTHROPIC_API_KEY": "sk-ant-ambient-key-999"}
    res_conflict = ApiKeyPrecedenceDetector.detect_conflicts(
        active_provider="anthropic",
        is_subscription_route=True,
        env_dict=fake_env,
    )
    assert res_conflict.has_conflict is True
    assert "ANTHROPIC_API_KEY" in res_conflict.detected_env_vars
    assert res_conflict.warning_message is not None

    # Safe case: no ambient env var
    res_clean = ApiKeyPrecedenceDetector.detect_conflicts(
        active_provider="anthropic",
        is_subscription_route=True,
        env_dict={},
    )
    assert res_clean.has_conflict is False
