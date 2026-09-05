"""Tests for environment variable sanitization (validator.sanitize_env)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.validator import (
    EnvInheritPolicy,
    sanitize_env,
)


class TestSanitizeEnvDefaultPolicy:
    """Default ALL policy — filter dangerous, keep rest."""

    def test_safe_vars_pass(self) -> None:
        env = {"HOME": "/home/user", "LANG": "en_US.UTF-8", "MY_APP": "value"}
        result = sanitize_env(env)
        assert result == env

    def test_exact_match_blocked(self) -> None:
        env = {"HOME": "/home/user", "LD_PRELOAD": "/evil.so"}
        result = sanitize_env(env)
        assert "LD_PRELOAD" not in result
        assert "HOME" in result

    def test_vault_master_key_blocked(self) -> None:
        env = {"HOME": "/home/user", "MYRM_VAULT_MASTER_KEY": "super-secret-key"}
        result = sanitize_env(env)
        assert "MYRM_VAULT_MASTER_KEY" not in result
        assert "HOME" in result

    def test_prefix_match_blocked(self) -> None:
        env = {"LD_CUSTOM": "value", "HOME": "/home/user"}
        result = sanitize_env(env)
        assert "LD_CUSTOM" not in result

    def test_dyld_prefix_blocked(self) -> None:
        env = {"DYLD_FALLBACK_LIBRARY_PATH": "/lib", "PATH": "/bin"}
        result = sanitize_env(env)
        assert "DYLD_FALLBACK_LIBRARY_PATH" not in result
        assert "PATH" in result


class TestWildcardExclusion:
    """Wildcard matching: *KEY*, *SECRET*, *TOKEN*, *PASSWORD*, *CREDENTIAL*."""

    def test_api_key_blocked(self) -> None:
        env = {"MY_API_KEY": "sk-123", "HOME": "/home"}
        result = sanitize_env(env)
        assert "MY_API_KEY" not in result
        assert "HOME" in result

    def test_secret_blocked(self) -> None:
        env = {"AWS_SECRET_ACCESS_KEY": "abc", "LANG": "C"}
        result = sanitize_env(env)
        assert "AWS_SECRET_ACCESS_KEY" not in result

    def test_token_blocked(self) -> None:
        env = {"GITHUB_TOKEN": "ghp_xxx", "USER": "me"}
        result = sanitize_env(env)
        assert "GITHUB_TOKEN" not in result

    def test_password_blocked(self) -> None:
        env = {"DB_PASSWORD": "pass123", "SHELL": "/bin/bash"}
        result = sanitize_env(env)
        assert "DB_PASSWORD" not in result

    def test_credential_blocked(self) -> None:
        env = {"MY_CREDENTIAL_FILE": "/path", "TERM": "xterm"}
        result = sanitize_env(env)
        assert "MY_CREDENTIAL_FILE" not in result

    def test_auth_and_bearer_and_signature_blocked(self) -> None:
        env = {
            "NOISE_AUTH_TOKEN": "noise-12345",
            "OAUTH_AUTHORIZATION_HEADER": "Bearer xxx",
            "BEARER_TOKEN": "bearer-secret",
            "AWS_SIGNATURE": "sig-hex",
            "NORMAL_PATH": "/usr/bin",
        }
        result = sanitize_env(env)
        assert "NOISE_AUTH_TOKEN" not in result
        assert "OAUTH_AUTHORIZATION_HEADER" not in result
        assert "BEARER_TOKEN" not in result
        assert "AWS_SIGNATURE" not in result
        assert "NORMAL_PATH" in result

    def test_case_insensitive_wildcard(self) -> None:
        env = {"my_api_key": "value", "My_Secret": "value2"}
        result = sanitize_env(env)
        assert "my_api_key" not in result
        assert "My_Secret" not in result

    def test_non_matching_safe_passes(self) -> None:
        env = {"MY_APP_CONFIG": "value", "CUSTOM_SETTING": "enabled"}
        result = sanitize_env(env)
        assert "MY_APP_CONFIG" in result
        assert "CUSTOM_SETTING" in result


class TestNonInheritableSecretsAndSockets:
    """Non-inheritable host secrets, DB connection URLs, and privileged sockets (Codex #38941 & #37607)."""

    def test_database_and_cache_urls_blocked(self) -> None:
        env = {
            "DATABASE_URL": "postgres://user:secret@db.internal:5432/main",
            "DATABASE_PRIVATE_URL": "mysql://root:pass@127.0.0.1/db",
            "REDIS_URL": "redis://:secret@redis.internal:6379",
            "REDIS_PRIVATE_URL": "redis://127.0.0.1:6379",
            "AMQP_URL": "amqp://guest:guest@localhost:5672",
            "MONGO_URL": "mongodb://admin:pass@mongodb:27017",
            "MY_SAFE_VAR": "keep_me",
        }
        result = sanitize_env(env)
        assert "DATABASE_URL" not in result
        assert "DATABASE_PRIVATE_URL" not in result
        assert "REDIS_URL" not in result
        assert "REDIS_PRIVATE_URL" not in result
        assert "AMQP_URL" not in result
        assert "MONGO_URL" not in result
        assert "MY_SAFE_VAR" in result

    def test_privileged_sockets_and_cluster_configs_blocked(self) -> None:
        env = {
            "SSH_AUTH_SOCK": "/tmp/ssh-agent.sock",
            "GPG_AGENT_INFO": "/tmp/gpg-agent.sock:1234:1",
            "KUBECONFIG": "/home/user/.kube/config",
            "DOCKER_CONFIG": "/home/user/.docker",
            "NETRC": "/home/user/.netrc",
            "HOME": "/home/user",
        }
        result = sanitize_env(env)
        assert "SSH_AUTH_SOCK" not in result
        assert "GPG_AGENT_INFO" not in result
        assert "KUBECONFIG" not in result
        assert "DOCKER_CONFIG" not in result
        assert "NETRC" not in result
        assert "HOME" in result

    def test_auth_headers_and_codex_tokens_blocked(self) -> None:
        env = {
            "AUTHORIZATION": "Bearer my-secret-token",
            "HTTP_AUTHORIZATION": "Basic admin:pass",
            "COOKIE": "session=abc12345",
            "HTTP_COOKIE": "token=secret",
            "CODEX_EXEC_SERVER_NOISE_AUTH_TOKEN": "codex-noise-secret",
            "OPENAI_IDENTITY_TOKEN_FILE": "/path/to/identity",
            "OPENAI_FEDERATION_RULE_ID": "rule-999",
            "MYRM_AGENT_SERVER_TOKEN": "myrm-srv-secret",
            "MYRM_CONTROL_PLANE_TOKEN": "myrm-cp-secret",
            "PATH": "/usr/bin:/bin",
        }
        result = sanitize_env(env)
        assert "AUTHORIZATION" not in result
        assert "HTTP_AUTHORIZATION" not in result
        assert "COOKIE" not in result
        assert "HTTP_COOKIE" not in result
        assert "CODEX_EXEC_SERVER_NOISE_AUTH_TOKEN" not in result
        assert "OPENAI_IDENTITY_TOKEN_FILE" not in result
        assert "OPENAI_FEDERATION_RULE_ID" not in result
        assert "MYRM_AGENT_SERVER_TOKEN" not in result
        assert "MYRM_CONTROL_PLANE_TOKEN" not in result
        assert "PATH" in result

    def test_case_insensitive_exact_keys_blocked(self) -> None:
        env = {
            "ssh_auth_sock": "/tmp/sock",
            "KubeConfig": "/etc/kube",
            "authorization": "Bearer token",
            "cookie": "sess=1",
            "database_url": "postgres://",
            "Codex_Exec_Server_Noise_Auth_Token": "secret",
            "PASS_PHRASE": "passphrase",
            "SAFE_ENV": "1",
        }
        result = sanitize_env(env)
        assert "ssh_auth_sock" not in result
        assert "KubeConfig" not in result
        assert "authorization" not in result
        assert "cookie" not in result
        assert "database_url" not in result
        assert "Codex_Exec_Server_Noise_Auth_Token" not in result
        assert "PASS_PHRASE" not in result
        assert "SAFE_ENV" in result


class TestBuildIsolatedChildEnvPostOverrideScrubbing:
    """Verify build_isolated_child_env cannot be bypassed via caller extra_env overrides."""

    def test_extra_env_cannot_reinject_host_credentials(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.env_isolation import (
            build_isolated_child_env,
        )

        extra = {
            "AUTHORIZATION": "Bearer evil",
            "SSH_AUTH_SOCK": "/tmp/hijack.sock",
            "DATABASE_URL": "mysql://root:evil@localhost",
            "NORMAL_CUSTOM_VAR": "permitted_value",
        }
        child_env = build_isolated_child_env(
            base_env={"PATH": "/bin", "HOME": "/home/user"},
            extra_env=extra,
            inherit_policy=EnvInheritPolicy.CORE,
        )
        assert "AUTHORIZATION" not in child_env
        assert "SSH_AUTH_SOCK" not in child_env
        assert "DATABASE_URL" not in child_env
        assert child_env.get("NORMAL_CUSTOM_VAR") == "permitted_value"
        assert child_env.get("PATH") == "/bin"


class TestCorePolicy:
    """CORE policy — only keep CORE_SAFE_ENV_VARS."""

    def test_core_vars_kept(self) -> None:
        env = {"HOME": "/home/user", "USER": "me", "PATH": "/bin", "CUSTOM": "val"}
        result = sanitize_env(env, inherit_policy=EnvInheritPolicy.CORE)
        assert "HOME" in result
        assert "USER" in result
        assert "PATH" in result
        assert "CUSTOM" not in result

    def test_dangerous_vars_blocked_even_in_core(self) -> None:
        env = {"HOME": "/home", "LD_PRELOAD": "/evil.so"}
        result = sanitize_env(env, inherit_policy=EnvInheritPolicy.CORE)
        assert "HOME" in result
        assert "LD_PRELOAD" not in result

    def test_xdg_vars_kept(self) -> None:
        env = {"XDG_RUNTIME_DIR": "/run/user/1000", "XDG_DATA_HOME": "/home/.local/share"}
        result = sanitize_env(env, inherit_policy=EnvInheritPolicy.CORE)
        assert "XDG_RUNTIME_DIR" in result
        assert "XDG_DATA_HOME" in result

    def test_empty_env(self) -> None:
        result = sanitize_env({}, inherit_policy=EnvInheritPolicy.CORE)
        assert result == {}


class TestNonePolicy:
    """NONE policy — return empty dict."""

    def test_all_vars_stripped(self) -> None:
        env = {"HOME": "/home", "USER": "me", "PATH": "/bin", "CUSTOM": "val"}
        result = sanitize_env(env, inherit_policy=EnvInheritPolicy.NONE)
        assert result == {}

    def test_empty_env(self) -> None:
        result = sanitize_env({}, inherit_policy=EnvInheritPolicy.NONE)
        assert result == {}
