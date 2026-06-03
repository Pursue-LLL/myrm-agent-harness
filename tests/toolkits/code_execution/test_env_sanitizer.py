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

    def test_case_insensitive_wildcard(self) -> None:
        env = {"my_api_key": "value", "My_Secret": "value2"}
        result = sanitize_env(env)
        assert "my_api_key" not in result
        assert "My_Secret" not in result

    def test_non_matching_wildcard_passes(self) -> None:
        env = {"MY_APP_CONFIG": "value", "DATABASE_URL": "postgres://"}
        result = sanitize_env(env)
        assert "MY_APP_CONFIG" in result
        assert "DATABASE_URL" in result


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
