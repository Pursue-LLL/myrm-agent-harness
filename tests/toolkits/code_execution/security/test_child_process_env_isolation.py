"""Unit and integration tests for ChildProcessCredentialTokenIsolation.

Validates that privileged host credentials (Noise auth tokens, Vault master keys,
API keys, database URLs) are strictly isolated and never leak to child processes,
while preserving developer toolchain variables and preventing dynamic injection attacks.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.security.env_isolation import (
    EnvInheritPolicy,
    build_isolated_child_env,
    sanitize_env,
)
from myrm_agent_harness.toolkits.code_execution.security.validator import (
    build_isolated_child_env as validator_build_isolated_child_env,
)
from myrm_agent_harness.toolkits.code_execution.security.validator import (
    sanitize_env as validator_sanitize_env,
)


class TestEnvIsolationCoreWhitelist:
    """Tests default CORE whitelist behavior."""

    def test_core_policy_preserves_safe_toolchain_vars(self) -> None:
        raw_env = {
            "PATH": "/usr/local/bin:/usr/bin",
            "HOME": "/home/developer",
            "USER": "developer",
            "LANG": "en_US.UTF-8",
            "TMPDIR": "/tmp/custom",
            "GOPATH": "/home/developer/go",
            "CARGO_HOME": "/home/developer/.cargo",
            "UNTRACKED_CUSTOM_VAR": "should_be_stripped_in_core",
        }
        sanitized = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.CORE)

        assert "PATH" in sanitized
        assert "HOME" in sanitized
        assert "USER" in sanitized
        assert "LANG" in sanitized
        assert "TMPDIR" in sanitized
        assert "GOPATH" in sanitized
        assert "CARGO_HOME" in sanitized
        # Non-whitelisted variable is dropped under CORE policy
        assert "UNTRACKED_CUSTOM_VAR" not in sanitized

    def test_core_and_all_policy_preserves_git_author_identity(self) -> None:
        raw_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "GIT_AUTHOR_NAME": "Developer One",
            "GIT_AUTHOR_EMAIL": "dev@example.com",
            "GIT_AUTHOR_DATE": "2026-09-05T12:00:00Z",
            "AUTH_HEADER": "Bearer secret_header",
            "OAUTH_AUTHORIZATION": "Bearer xxx",
        }
        # Under ALL policy: Git author preserved, secrets stripped
        sanitized_all = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.ALL)
        assert sanitized_all["GIT_AUTHOR_NAME"] == "Developer One"
        assert sanitized_all["GIT_AUTHOR_EMAIL"] == "dev@example.com"
        assert sanitized_all["GIT_AUTHOR_DATE"] == "2026-09-05T12:00:00Z"
        assert "AUTH_HEADER" not in sanitized_all
        assert "OAUTH_AUTHORIZATION" not in sanitized_all

        # Under CORE policy: Git author in whitelist preserved, secrets dropped
        sanitized_core = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.CORE)
        assert sanitized_core["GIT_AUTHOR_NAME"] == "Developer One"
        assert sanitized_core["GIT_AUTHOR_EMAIL"] == "dev@example.com"
        assert sanitized_core["GIT_AUTHOR_DATE"] == "2026-09-05T12:00:00Z"
        assert "AUTH_HEADER" not in sanitized_core
        assert "OAUTH_AUTHORIZATION" not in sanitized_core

    def test_core_policy_case_insensitive_on_system_vars(self) -> None:
        raw_env = {
            "Path": "C:\\Windows\\system32",
            "Temp": "C:\\Users\\Admin\\AppData\\Local\\Temp",
            "SystemRoot": "C:\\Windows",
        }
        sanitized = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.CORE)
        assert len(sanitized) == 3
        assert "Path" in sanitized
        assert "Temp" in sanitized


class TestSensitiveSecretStripping:
    """Tests stripping of tokens, keys, passwords, and noise credentials."""

    def test_strips_noise_auth_tokens_and_vault_master_keys(self) -> None:
        raw_env = {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "NOISE_AUTH_TOKEN": "noise_secret_handshake_token_12345",
            "NOISE_PRIVATE_KEY": "noise_curve25519_key_abcde",
            "MYRM_VAULT_MASTER_KEY": "super_vault_master_pass_9999",
            "DATABASE_URL": "postgresql://postgres:secretpassword@localhost:5432/db",
            "DATABASE_PASSWORD": "secretpassword",
            "REDIS_URL": "redis://:secretredis@localhost:6379",
        }
        sanitized = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.ALL)

        assert "PATH" in sanitized
        assert "HOME" in sanitized
        assert "NOISE_AUTH_TOKEN" not in sanitized
        assert "NOISE_PRIVATE_KEY" not in sanitized
        assert "MYRM_VAULT_MASTER_KEY" not in sanitized
        assert "DATABASE_URL" not in sanitized
        assert "DATABASE_PASSWORD" not in sanitized
        assert "REDIS_URL" not in sanitized

    def test_strips_mixed_case_sensitive_wildcards(self) -> None:
        raw_env = {
            "PATH": "/bin",
            "openAiApiKey": "sk-proj-12345678",
            "MySecretToken": "token-999",
            "db_password": "pass",
            "USER_AUTH_HEADER": "Bearer abc",
            "bearer_credential": "xyz",
            "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_1234567890",
        }
        sanitized = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.ALL)

        assert "PATH" in sanitized
        assert "openAiApiKey" not in sanitized
        assert "MySecretToken" not in sanitized
        assert "db_password" not in sanitized
        assert "USER_AUTH_HEADER" not in sanitized
        assert "bearer_credential" not in sanitized
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" not in sanitized

    def test_strips_dynamic_linker_and_interpreter_injection(self) -> None:
        raw_env = {
            "PATH": "/usr/bin",
            "LD_PRELOAD": "/tmp/evil.so",
            "LD_LIBRARY_PATH": "/tmp/evil_libs",
            "DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib",
            "DYLD_LIBRARY_PATH": "/tmp/evil_frameworks",
            "NODE_OPTIONS": "--require /tmp/malicious.js",
            "PYTHONSTARTUP": "/tmp/run_on_python_start.py",
            "SSLKEYLOGFILE": "/tmp/keys.log",
        }
        sanitized = sanitize_env(raw_env, inherit_policy=EnvInheritPolicy.ALL)

        assert "PATH" in sanitized
        assert "LD_PRELOAD" not in sanitized
        assert "LD_LIBRARY_PATH" not in sanitized
        assert "DYLD_INSERT_LIBRARIES" not in sanitized
        assert "DYLD_LIBRARY_PATH" not in sanitized
        assert "NODE_OPTIONS" not in sanitized
        assert "PYTHONSTARTUP" not in sanitized
        assert "SSLKEYLOGFILE" not in sanitized


class TestBuildIsolatedChildEnvOverrides:
    """Tests build_isolated_child_env with explicit caller extras."""

    def test_allows_safe_extra_env_while_blocking_injection_overrides(self) -> None:
        base_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "OPENAI_API_KEY": "sk-leak-me",
        }
        extra_env = {
            "APP_BUILD_ENV": "production",
            "TARGET_ARCH": "x86_64",
            "LD_PRELOAD": "/tmp/injected.so",  # Malicious override attempt!
            "PYTHONSTARTUP": "/tmp/hijack.py",  # Malicious override attempt!
        }
        child_env = build_isolated_child_env(
            base_env=base_env,
            extra_env=extra_env,
            inherit_policy=EnvInheritPolicy.CORE,
        )

        assert child_env["PATH"] == "/usr/bin"
        assert child_env["HOME"] == "/home/user"
        assert "OPENAI_API_KEY" not in child_env
        assert child_env["APP_BUILD_ENV"] == "production"
        assert child_env["TARGET_ARCH"] == "x86_64"
        # Injection overrides are strictly rejected
        assert "LD_PRELOAD" not in child_env
        assert "PYTHONSTARTUP" not in child_env

    def test_internal_ptc_keys_safely_permitted(self) -> None:
        base_env = {
            "PATH": "/usr/bin",
            "_MYRM_PTC_SOCKET": "/tmp/ptc_bridge.sock",
            "_MYRM_PTC_PORT": "9090",
            "_MYRM_PTC_TIMEOUT": "30",
        }
        child_env = build_isolated_child_env(base_env=base_env, inherit_policy=EnvInheritPolicy.CORE)
        assert child_env["_MYRM_PTC_SOCKET"] == "/tmp/ptc_bridge.sock"
        assert child_env["_MYRM_PTC_PORT"] == "9090"
        assert child_env["_MYRM_PTC_TIMEOUT"] == "30"


class TestCallsiteIntegrationParity:
    """Tests integration with LocalPersistentSession environment creation."""

    def test_local_persistent_session_environment_blocks_host_secrets(self) -> None:
        toxic_host_env = {
            "PATH": "/usr/local/bin:/usr/bin",
            "HOME": "/Users/developer",
            "USER": "developer",
            "LANG": "en_US.UTF-8",
            "MYRM_VAULT_MASTER_KEY": "vault-master-123456",
            "NOISE_AUTH_TOKEN": "noise-token-7890",
            "OPENAI_API_KEY": "sk-proj-host-openai-secret",
            "DEEPSEEK_API_KEY": "sk-deepseek-host-secret",
            "DATABASE_URL": "postgresql://root:secret@127.0.0.1:5432/myrm",
            "OTHER_RANDOM_SECRET_VAR": "secret_data",
        }
        with patch.dict(os.environ, toxic_host_env, clear=True):
            isolated_env = build_isolated_child_env(inherit_policy=EnvInheritPolicy.CORE)

            assert "PATH" in isolated_env
            assert "HOME" in isolated_env
            assert "MYRM_VAULT_MASTER_KEY" not in isolated_env
            assert "NOISE_AUTH_TOKEN" not in isolated_env
            assert "OPENAI_API_KEY" not in isolated_env
            assert "DEEPSEEK_API_KEY" not in isolated_env
            assert "DATABASE_URL" not in isolated_env
            assert "OTHER_RANDOM_SECRET_VAR" not in isolated_env

    def test_validator_backward_compatibility_reexports(self) -> None:
        raw_env = {
            "PATH": "/usr/bin",
            "API_KEY": "secret",
            "USER_TOKEN": "abc",
        }
        sanitized_1 = sanitize_env(raw_env)
        sanitized_2 = validator_sanitize_env(raw_env)
        assert sanitized_1 == sanitized_2
        assert "API_KEY" not in sanitized_2
        assert "USER_TOKEN" not in sanitized_2

        built_1 = build_isolated_child_env(base_env=raw_env)
        built_2 = validator_build_isolated_child_env(base_env=raw_env)
        assert built_1 == built_2


class TestExecutorAndHookSubprocessIsolation:
    """Tests isolation across LocalExecutor, background spawn, and Command Hooks."""

    def test_local_executor_build_env_scrubs_user_env_injection(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
        from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor

        executor = LocalExecutor(config=ExecutionConfig(), workspace_path="/tmp")
        user_env = {
            "SSH_AUTH_SOCK": "/tmp/evil.sock",
            "DATABASE_URL": "postgres://root:evil@localhost",
            "CUSTOM_DEV_VAR": "valid_value",
        }
        with patch.dict(os.environ, {"PATH": "/usr/bin", "AUTHORIZATION": "Bearer host_token"}):
            built_env = executor._build_bash_env(user_env=user_env)

            assert "AUTHORIZATION" not in built_env
            assert "SSH_AUTH_SOCK" not in built_env
            assert "DATABASE_URL" not in built_env
            assert built_env.get("CUSTOM_DEV_VAR") == "valid_value"

    def test_background_spawn_post_override_scrubs_context_env(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.env_isolation import (
            is_non_inheritable_env_var,
        )

        malicious_context_env = {
            "LD_PRELOAD": "/tmp/rootkit.so",
            "KUBECONFIG": "/root/.kube/config",
            "REDIS_URL": "redis://:secret@cache:6379",
            "BUILD_STEP": "compile",
        }
        cleaned_env = validator_sanitize_env(malicious_context_env)
        for k in list(cleaned_env.keys()):
            if is_non_inheritable_env_var(k):
                cleaned_env.pop(k, None)

        assert "LD_PRELOAD" not in cleaned_env
        assert "KUBECONFIG" not in cleaned_env
        assert "REDIS_URL" not in cleaned_env
        assert cleaned_env.get("BUILD_STEP") == "compile"

    def test_ptc_orchestration_allows_pythonpath(self) -> None:
        env_with_ptc = {
            "PATH": "/usr/bin",
            "_MYRM_PTC_SOCKET": "/tmp/ptc.sock",
            "PYTHONPATH": "/opt/custom/lib",
        }
        res = sanitize_env(env_with_ptc, inherit_policy=EnvInheritPolicy.ALL)
        assert res.get("PYTHONPATH") == "/opt/custom/lib"

    def test_build_isolated_child_env_post_override_scrubs_case_variants(self) -> None:
        # Construct an env where an override attempts to inject a mixed-case credential
        res = build_isolated_child_env(
            base_env={"PATH": "/usr/bin"},
            extra_env={"Auth_Token": "leak_me", "NORMAL_VAR": "val"},
            inherit_policy=EnvInheritPolicy.CORE,
        )
        assert "Auth_Token" not in res
        assert res.get("NORMAL_VAR") == "val"

    @pytest.mark.asyncio
    async def test_command_hook_execution_strips_host_credentials(self) -> None:
        """Integration test: CommandHookDefinition execution strips parent env secrets."""
        from myrm_agent_harness.agent.hooks.executor import HookExecutor
        from myrm_agent_harness.agent.hooks.types import CommandHookDefinition

        executor = HookExecutor()
        # A command hook printing environment variables to stdout
        hook = CommandHookDefinition(
            command="python3 -c 'import os, json; print(json.dumps(dict(os.environ)))'",
            timeout_seconds=5,
        )
        toxic_host = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "AUTHORIZATION": "Bearer super_secret_hook_token",
            "DATABASE_URL": "postgres://user:pass@internal-db:5432",
            "SSH_AUTH_SOCK": "/tmp/ssh_hook.sock",
            "MYRM_VAULT_MASTER_KEY": "hook_vault_key",
        }
        with patch.dict(os.environ, toxic_host, clear=True):
            res = await executor._run_command(hook=hook, event="tool_preflight", payload={"test": 123})
            assert res.success is True
            # Parse output json
            import json
            hook_env = json.loads(res.output)
            assert "AUTHORIZATION" not in hook_env
            assert "DATABASE_URL" not in hook_env
            assert "SSH_AUTH_SOCK" not in hook_env
            assert "MYRM_VAULT_MASTER_KEY" not in hook_env
            assert hook_env.get("HOOK_EVENT") == "tool_preflight"

