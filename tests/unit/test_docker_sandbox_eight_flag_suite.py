"""Unit tests for Docker Sandbox 8-Flag Hardening and Vault-Proxy Suite."""

from myrm_agent_harness.core.security.sandbox_hardening import (
    EightFlagBuilder,
    EightFlagSandboxConfig,
    HostVaultProxy,
    LazySandboxLifecycleManager,
    NetworkIsolationMode,
    ProvisionStatus,
    VaultProxyRequest,
)


def test_eight_flag_command_generation_and_verification() -> None:
    config = EightFlagSandboxConfig(
        read_only=True,
        tmp_size_mb=100,
        tmp_noexec=True,
        pids_limit=100,
        cap_drop_all=True,
        no_new_privileges=True,
        user="1000:1000",
        network_mode=NetworkIsolationMode.NONE,
        memory_limit="512m",
        cpus_quota=1.0,
        auto_remove=True,
    )
    builder = EightFlagBuilder(config)
    cmd = builder.build_run_args(
        image="ghcr.io/myrm-ai/sandbox-python:3.12",
        command=["python3", "main.py"],
    )

    assert cmd.flags_verified
    assert len(cmd.missing_flags) == 0

    args = cmd.raw_args
    assert "--read-only" in args
    assert "--tmpfs=/tmp:size=100m,noexec" in args
    assert "--pids-limit=100" in args
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges" in args
    assert "--user=1000:1000" in args
    assert "--network=none" in args
    assert "--memory=512m" in args
    assert "--cpus=1.0" in args
    assert "--rm" in args
    assert args[-2:] == ["python3", "main.py"]


def test_eight_flag_missing_detection() -> None:
    builder = EightFlagBuilder()
    # Incomplete arguments missing read-only and noexec
    incomplete_args = [
        "docker",
        "run",
        "--tmpfs=/tmp:size=100m",
        "--pids-limit=100",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=1000:1000",
        "--network=none",
        "--memory=512m",
        "--cpus=1.0",
        "alpine:latest",
    ]
    verified, missing = builder.verify_flags(incomplete_args)
    assert not verified
    assert "FLAG_1_READ_ONLY" in missing
    assert "FLAG_2_TMPFS_NOEXEC" in missing


def test_plaintext_env_leak_detection() -> None:
    builder = EightFlagBuilder()

    # Leaking API Key and Token
    leaky_env = [
        "-e",
        "GITHUB_TOKEN=ghp_secrettoken123456",
        "--env",
        "ANTHROPIC_API_KEY=sk-ant-api03-abcdef",
        "-e",
        "PYTHONUNBUFFERED=1",
    ]
    is_safe, leaks = builder.check_leak_free_env(leaky_env)
    assert not is_safe
    assert len(leaks) == 2

    # Clean env
    safe_env = ["-e", "PYTHONUNBUFFERED=1", "--env", "APP_ENV=production"]
    is_clean, clean_leaks = builder.check_leak_free_env(safe_env)
    assert is_clean
    assert len(clean_leaks) == 0


def test_vault_proxy_domain_allowlist_and_injection() -> None:
    vault = HostVaultProxy()
    vault.register_credential(
        credential_id="cred_github_sync",
        target_service="GitHub API",
        secret_value="ghp_real_secret_token_not_in_sandbox",
        allowed_domains=["api.github.com", "github.com"],
        description="Sync repo access",
    )

    # 1. Inspect metadata: secret is strictly redacted
    meta = vault.get_credential_metadata("cred_github_sync")
    assert meta is not None
    assert meta.secret_value == "[REDACTED_IN_VAULT]"

    # 2. Permitted domain request
    allowed_req = VaultProxyRequest(
        project_id="proj_alpha",
        target_url="https://api.github.com/repos/myrm/core",
        method="GET",
        credential_id="cred_github_sync",
    )
    resp_allowed = vault.process_outbound_request(allowed_req)
    assert resp_allowed.status_code == 200
    assert resp_allowed.credential_injected
    assert resp_allowed.blocked_reason is None

    # 3. Blocked forbidden domain request (preventing SSRF/data exfiltration)
    evil_req = VaultProxyRequest(
        project_id="proj_alpha",
        target_url="https://malicious.evil.com/exfiltrate",
        method="POST",
        credential_id="cred_github_sync",
    )
    resp_blocked = vault.process_outbound_request(evil_req)
    assert resp_blocked.status_code == 403
    assert not resp_blocked.credential_injected
    assert "not permitted" in (resp_blocked.blocked_reason or "")


def test_lazy_sandbox_lifecycle() -> None:
    lifecycle = LazySandboxLifecycleManager()
    assert lifecycle.status == ProvisionStatus.UNINITIALIZED
    assert lifecycle.container_id is None

    # 1. Dynamically provision on first execution demand
    cmd = lifecycle.ensure_provisioned(image="python:3.12-slim")
    assert lifecycle.status == ProvisionStatus.RUNNING
    assert lifecycle.container_id is not None
    assert cmd.flags_verified

    # 2. Idempotent call returns active container spec
    cmd_again = lifecycle.ensure_provisioned(image="python:3.12-slim")
    assert cmd_again == cmd

    # 3. Dispose sandbox cleanly
    lifecycle.dispose()
    assert lifecycle.status == ProvisionStatus.DISPOSED
    assert lifecycle.container_id is None
