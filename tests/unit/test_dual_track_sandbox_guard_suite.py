"""Unit tests for Dual-Track Soft Memory vs Hard Redline Sandbox Guard Suite."""

from __future__ import annotations

import base64
import time

from myrm_agent_harness.core.security.dual_track_sandbox_guard import (
    DualTrackSandboxGuard,
    HardRedlineRule,
    InterceptionVerdict,
    RedlineCategory,
    RedlinePolicyCompiler,
    SoftMemoryRecord,
)


def test_policy_compiler_baseline_and_custom() -> None:
    compiler = RedlinePolicyCompiler()
    policy = compiler.compile()

    assert policy.rule_count >= 10
    assert "**/.env*" in policy.blocked_file_patterns
    assert "**/id_rsa*" in policy.blocked_file_patterns

    # Add custom rule
    custom_rule = HardRedlineRule(
        rule_id="RL-FILE-099",
        category=RedlineCategory.FILE_PROTECTION,
        pattern="**/*.p12",
        description="Block PKCS#12 archive access",
    )
    compiler.register_rule(custom_rule)
    updated_policy = compiler.compile()

    assert updated_policy.rule_count == policy.rule_count + 1
    assert "**/*.p12" in updated_policy.blocked_file_patterns


def test_file_access_interception() -> None:
    guard = DualTrackSandboxGuard()

    # 1. Blocked protected files
    res_env = guard.evaluate_file_access(".env")
    assert res_env.is_permitted is False
    assert res_env.verdict == InterceptionVerdict.BLOCKED_HARD_REDLINE_FILE
    assert res_env.blocked_by_rule_id == "RL-FILE-001"

    res_nested_env = guard.evaluate_file_access("configs/secrets/.env.production")
    assert res_nested_env.is_permitted is False
    assert res_nested_env.verdict == InterceptionVerdict.BLOCKED_HARD_REDLINE_FILE

    res_pem = guard.evaluate_file_access("/etc/ssl/certs/server.pem")
    assert res_pem.is_permitted is False
    assert res_pem.verdict == InterceptionVerdict.BLOCKED_HARD_REDLINE_FILE

    # 2. Poison / Null-byte evasion attempt
    res_null = guard.evaluate_file_access("docs/safe.txt\x00.env")
    assert res_null.is_permitted is False
    assert res_null.verdict == InterceptionVerdict.BLOCKED_EVASION_ATTEMPT

    # 3. Permitted normal workspace files
    res_normal = guard.evaluate_file_access("src/main.py")
    assert res_normal.is_permitted is True
    assert res_normal.verdict == InterceptionVerdict.PERMITTED


def test_command_execution_interception() -> None:
    guard = DualTrackSandboxGuard()

    # 1. Destructive system commands
    res_rm = guard.evaluate_command_execution("rm -rf /")
    assert res_rm.is_permitted is False
    assert res_rm.verdict == InterceptionVerdict.BLOCKED_HARD_REDLINE_COMMAND
    assert res_rm.blocked_by_rule_id == "RL-CMD-001"

    # 2. Fork bomb pattern
    res_fork = guard.evaluate_command_execution(":(){ :|:& };:")
    assert res_fork.is_permitted is False
    assert res_fork.verdict == InterceptionVerdict.BLOCKED_HARD_REDLINE_COMMAND

    # 3. Direct reference to .env in shell command
    res_cat_env = guard.evaluate_command_execution("cat .env")
    assert res_cat_env.is_permitted is False
    assert res_cat_env.verdict == InterceptionVerdict.BLOCKED_HARD_REDLINE_FILE

    # 4. Obfuscated base64 evasion attempt (echo 'cat .env' | base64 -d | bash)
    encoded = base64.b64encode(b"cat .env").decode("ascii")
    evasion_cmd = f"echo '{encoded}' | base64 -d | bash"
    res_evasion = guard.evaluate_command_execution(evasion_cmd)
    assert res_evasion.is_permitted is False
    assert res_evasion.verdict == InterceptionVerdict.BLOCKED_EVASION_ATTEMPT

    # 5. Permitted development command
    res_safe = guard.evaluate_command_execution("pytest tests/unit")
    assert res_safe.is_permitted is True
    assert res_safe.verdict == InterceptionVerdict.PERMITTED


def test_soft_memory_decoupling_and_decay() -> None:
    now = time.time()
    # Recent memory with high recall weight
    mem_fresh = SoftMemoryRecord(
        memory_id="mem-1",
        content="User prefers concise TypeScript definitions",
        recall_weight=0.9,
        decay_rate=0.01,
        last_accessed=now,
    )
    assert mem_fresh.compute_effective_weight(now) == 0.9

    # Old memory with high decay
    mem_stale = SoftMemoryRecord(
        memory_id="mem-2",
        content="Temporary debug preference from 200 hours ago",
        recall_weight=0.5,
        decay_rate=0.05,
        last_accessed=now - (200 * 3600),
    )
    # Effective weight should decay to minimum boundary (0.1 * 0.5 = 0.05)
    assert mem_stale.compute_effective_weight(now) < 0.1

    filtered = DualTrackSandboxGuard.filter_soft_memories([mem_fresh, mem_stale], min_weight=0.2)
    assert len(filtered) == 1
    assert filtered[0].memory_id == "mem-1"
