"""
[POS] tests/unit/test_hardened_sandbox_perimeter_suite.py
[INPUT] myrm_agent_harness.core.security.hardened_sandbox_perimeter
[OUTPUT] unit tests

Unit tests for ScaleReadyHardenedAgentSandboxAndSafetyPerimeterSuite.
Strict typing applied: No `Any` types allowed.
"""

from myrm_agent_harness.core.security.hardened_sandbox_perimeter import (
    EgressTarget,
    EgressVerdictEnum,
    HardenedSandboxPerimeterSuite,
    HardenedSandboxSpec,
    ProcessUsageSnapshot,
    RuntimeSpecValidationVerdictEnum,
    SandboxIsolationModeEnum,
)


def mock_dns_resolver(hostname: str) -> list[str]:
    """Deterministic mock DNS resolver for offline unit tests."""
    mapping: dict[str, list[str]] = {
        "api.openai.com": ["104.18.7.192"],
        "api.github.com": ["140.82.121.4"],
        "evil-rebinding.internal": ["10.0.1.50"],
        "metadata.attacker.com": ["169.254.169.254"],
    }
    return mapping.get(hostname, [])


def test_runtime_spec_validation() -> None:
    suite = HardenedSandboxPerimeterSuite()

    # 1. Valid production-hardened specification
    valid_spec = HardenedSandboxSpec(
        isolation_mode=SandboxIsolationModeEnum.CONTAINER,
        is_non_root=True,
        uid=1001,
        gid=1001,
        read_only_rootfs=True,
        tmpfs_noexec=True,
        persistent_volume_path="/data/volume-01",
        memory_limit_mb=1024,
        cpu_quota_pct=2.0,
        pids_max=256,
    )
    res_valid = suite.validate_runtime_spec(valid_spec)
    assert res_valid.is_valid is True
    assert res_valid.verdict == RuntimeSpecValidationVerdictEnum.VALID
    assert len(res_valid.violations) == 0

    # 2. Dangerous root execution
    bad_root_spec = HardenedSandboxSpec(is_non_root=False, uid=0)
    res_root = suite.validate_runtime_spec(bad_root_spec)
    assert res_root.is_valid is False
    assert res_root.verdict == RuntimeSpecValidationVerdictEnum.INVALID_ROOT_USER

    # 3. Writable rootfs
    bad_rootfs_spec = HardenedSandboxSpec(read_only_rootfs=False)
    res_rootfs = suite.validate_runtime_spec(bad_rootfs_spec)
    assert res_rootfs.is_valid is False
    assert res_rootfs.verdict == RuntimeSpecValidationVerdictEnum.INVALID_WRITABLE_ROOTFS

    # 4. Missing tmpfs noexec
    bad_tmpfs_spec = HardenedSandboxSpec(tmpfs_noexec=False)
    res_tmpfs = suite.validate_runtime_spec(bad_tmpfs_spec)
    assert res_tmpfs.is_valid is False
    assert res_tmpfs.verdict == RuntimeSpecValidationVerdictEnum.INVALID_MISSING_TMPFS_NOEXEC

    # 5. Dangerous resource bounds
    bad_bounds_spec = HardenedSandboxSpec(pids_max=5)
    res_bounds = suite.validate_runtime_spec(bad_bounds_spec)
    assert res_bounds.is_valid is False
    assert res_bounds.verdict == RuntimeSpecValidationVerdictEnum.INVALID_RESOURCE_BOUNDS


def test_ssrf_egress_shield() -> None:
    suite = HardenedSandboxPerimeterSuite(dns_resolver_fn=mock_dns_resolver)

    # 1. Valid public egress
    target_good = EgressTarget(host="api.openai.com", port=443)
    res_good = suite.evaluate_egress(target_good)
    assert res_good.is_allowed is True
    assert res_good.verdict == EgressVerdictEnum.ALLOWED
    assert res_good.resolved_ip == "104.18.7.192"

    # 2. Block direct cloud metadata access (169.254.169.254)
    target_metadata = EgressTarget(host="169.254.169.254", port=80)
    res_metadata = suite.evaluate_egress(target_metadata)
    assert res_metadata.is_allowed is False
    assert res_metadata.verdict == EgressVerdictEnum.BLOCKED_CLOUD_METADATA

    # 3. Block private RFC 1918 subnets
    target_private = EgressTarget(host="10.244.0.15", port=8080)
    res_private = suite.evaluate_egress(target_private)
    assert res_private.is_allowed is False
    assert res_private.verdict == EgressVerdictEnum.BLOCKED_PRIVATE_IP

    # 4. Block DNS rebinding to private subnet
    target_rebinding = EgressTarget(host="evil-rebinding.internal", port=443)
    res_rebinding = suite.evaluate_egress(target_rebinding)
    assert res_rebinding.is_allowed is False
    assert res_rebinding.verdict == EgressVerdictEnum.BLOCKED_PRIVATE_IP
    assert res_rebinding.resolved_ip == "10.0.1.50"

    # 5. Block DNS rebinding to metadata endpoint
    target_dns_meta = EgressTarget(host="metadata.attacker.com", port=80)
    res_dns_meta = suite.evaluate_egress(target_dns_meta)
    assert res_dns_meta.is_allowed is False
    assert res_dns_meta.verdict == EgressVerdictEnum.BLOCKED_CLOUD_METADATA

    # 6. Domain allowlist filtering
    target_allowlist = EgressTarget(host="api.github.com", port=443)
    res_disallowed_domain = suite.evaluate_egress(
        target_allowlist, allowlisted_domains=["openai.com"]
    )
    assert res_disallowed_domain.is_allowed is False
    assert res_disallowed_domain.verdict == EgressVerdictEnum.BLOCKED_DOMAIN_NOT_ALLOWLISTED

    res_allowed_domain = suite.evaluate_egress(
        target_allowlist, allowlisted_domains=["github.com"]
    )
    assert res_allowed_domain.is_allowed is True
    assert res_allowed_domain.verdict == EgressVerdictEnum.ALLOWED


def test_credential_broker() -> None:
    suite = HardenedSandboxPerimeterSuite()

    # 1. Register master secrets
    suite.register_secret("openai_key", "sk-proj-super-secret-master-token")
    suite.register_secret("db_pass", "postgres-super-pass")
    assert suite.has_secret("openai_key") is True
    assert suite.has_secret("non_existent") is False

    # 2. Mint short-lived scoped ticket
    ticket = suite.mint_ephemeral_ticket(
        secret_alias="openai_key",
        allowed_scopes=["llm:chat", "llm:embeddings"],
        ttl_seconds=120.0,
    )
    assert ticket.ticket_id.startswith("tkt-")
    assert ticket.ephemeral_token.startswith("ept-")
    assert "llm:chat" in ticket.allowed_scopes

    # 3. Verify valid ticket with scope
    assert suite.verify_ticket(ticket.ticket_id, required_scope="llm:chat") is True
    assert suite.verify_ticket(ticket.ticket_id, required_scope="admin:drop_db") is False

    # 4. Revocation
    assert suite.revoke_ticket(ticket.ticket_id) is True
    assert suite.verify_ticket(ticket.ticket_id) is False


def test_resource_process_guard_and_fork_bomb() -> None:
    suite = HardenedSandboxPerimeterSuite()
    agent_id = "agent-forkbomb-test"

    # 1. Normal resource consumption
    snap_normal = ProcessUsageSnapshot(
        active_pids_count=12,
        memory_used_mb=120.0,
        cpu_percent=15.0,
    )
    is_safe, _ = suite.evaluate_process_usage(
        agent_id, snap_normal, pids_max=64, memory_limit_mb=512.0
    )
    assert is_safe is True
    assert suite.is_process_guard_tripped(agent_id) is False

    # 2. Fork bomb outbreak exceeding pids_max
    snap_forkbomb = ProcessUsageSnapshot(
        active_pids_count=100,
        memory_used_mb=250.0,
        cpu_percent=99.0,
    )
    is_safe_fb, msg_fb = suite.evaluate_process_usage(
        agent_id, snap_forkbomb, pids_max=64, memory_limit_mb=512.0
    )
    assert is_safe_fb is False
    assert "Fork bomb detected" in msg_fb
    assert suite.is_process_guard_tripped(agent_id) is True

    # 3. Subsequent attempts remain tripped
    is_safe_sub, _ = suite.evaluate_process_usage(
        agent_id, snap_normal, pids_max=64, memory_limit_mb=512.0
    )
    assert is_safe_sub is False

    # 4. Reset process guard
    assert suite.reset_process_guard(agent_id) is True
    assert suite.is_process_guard_tripped(agent_id) is False


def test_facade_metrics_telemetry() -> None:
    suite = HardenedSandboxPerimeterSuite(dns_resolver_fn=mock_dns_resolver)

    # Perform operations to advance counters
    suite.validate_runtime_spec(HardenedSandboxSpec())
    suite.validate_runtime_spec(HardenedSandboxSpec(is_non_root=False, uid=0))

    suite.evaluate_egress(EgressTarget(host="api.openai.com"))
    suite.evaluate_egress(EgressTarget(host="169.254.169.254"))

    suite.register_secret("test_sec", "val")
    suite.mint_ephemeral_ticket("test_sec", ["read"])

    suite.evaluate_process_usage(
        "agent-fb-metric",
        ProcessUsageSnapshot(active_pids_count=300, memory_used_mb=100.0, cpu_percent=80.0),
        pids_max=64,
    )

    metrics = suite.get_metrics()
    assert metrics.total_spec_validations == 2
    assert metrics.spec_validation_failures == 1
    assert metrics.egress_requests_evaluated == 2
    assert metrics.ssrf_blocks == 1
    assert metrics.credential_tickets_minted == 1
    assert metrics.fork_bomb_mitigations == 1
