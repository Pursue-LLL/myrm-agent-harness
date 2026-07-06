"""End-to-end integration tests for security risk classifier through evaluate_tool_call.

Verifies that the full security evaluation pipeline correctly auto-allows SAFE
commands and requires confirmation for UNKNOWN commands. Tests cover:
- Simple safe commands (ls, cat, grep)
- Git read-only commands via SubcommandConfig
- Newly added tool configs (npm/pip/docker/cargo/kubectl/uv/bun/pnpm)
- Shell operator splitting (&&, ||, |)
- Dangerous commands remain UNKNOWN
- Safe write operations (npm install bare, uv sync)
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.engine import evaluate_tool_call
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    SecurityConfig,
)

_CONFIG = SecurityConfig()


def _eval_shell(command: str) -> PermissionAction:
    """Evaluate a shell_exec command through the full security pipeline."""
    action, _ = evaluate_tool_call(
        "shell_exec",
        {"command": command},
        _CONFIG,
    )
    return action


class TestAutoAllowSafeCommands:
    """SAFE commands should be auto-allowed without user confirmation."""

    def test_ls(self) -> None:
        assert _eval_shell("ls -la") == PermissionAction.ALLOW

    def test_cat(self) -> None:
        assert _eval_shell("cat file.txt") == PermissionAction.ALLOW

    def test_grep_pipe(self) -> None:
        assert _eval_shell("cat file | grep pattern") == PermissionAction.ALLOW

    def test_git_status(self) -> None:
        assert _eval_shell("git status") == PermissionAction.ALLOW

    def test_git_log_oneline(self) -> None:
        assert _eval_shell("git log --oneline -10") == PermissionAction.ALLOW

    def test_git_diff_cached(self) -> None:
        assert _eval_shell("git diff --cached") == PermissionAction.ALLOW

    def test_git_branch_list(self) -> None:
        assert _eval_shell("git branch -a") == PermissionAction.ALLOW


class TestAutoAllowNewTools:
    """Newly added tool configs should auto-allow safe subcommands."""

    def test_npm_list(self) -> None:
        assert _eval_shell("npm list") == PermissionAction.ALLOW

    def test_npm_outdated(self) -> None:
        assert _eval_shell("npm outdated") == PermissionAction.ALLOW

    def test_npm_install_bare(self) -> None:
        assert _eval_shell("npm install") == PermissionAction.ALLOW

    def test_pip_list(self) -> None:
        assert _eval_shell("pip list --outdated") == PermissionAction.ALLOW

    def test_pip_freeze(self) -> None:
        assert _eval_shell("pip freeze") == PermissionAction.ALLOW

    def test_pip_install_requirements(self) -> None:
        assert _eval_shell("pip install -r requirements.txt") == PermissionAction.ALLOW

    def test_uv_sync(self) -> None:
        assert _eval_shell("uv sync --all-extras") == PermissionAction.ALLOW

    def test_uv_pip_list(self) -> None:
        assert _eval_shell("uv pip list") == PermissionAction.ALLOW

    def test_docker_ps(self) -> None:
        assert _eval_shell("docker ps -a") == PermissionAction.ALLOW

    def test_docker_images(self) -> None:
        assert _eval_shell("docker images") == PermissionAction.ALLOW

    def test_kubectl_get_pods(self) -> None:
        assert _eval_shell("kubectl get pods") == PermissionAction.ALLOW

    def test_cargo_build(self) -> None:
        assert _eval_shell("cargo build --release") == PermissionAction.ALLOW

    def test_cargo_check(self) -> None:
        assert _eval_shell("cargo check") == PermissionAction.ALLOW

    def test_cargo_test(self) -> None:
        assert _eval_shell("cargo test") == PermissionAction.ALLOW

    def test_bun_install_bare(self) -> None:
        assert _eval_shell("bun install") == PermissionAction.ALLOW

    def test_pnpm_list(self) -> None:
        assert _eval_shell("pnpm list --json") == PermissionAction.ALLOW

    def test_npm_run_build(self) -> None:
        assert _eval_shell("npm run build") == PermissionAction.ALLOW

    def test_npm_test(self) -> None:
        assert _eval_shell("npm test") == PermissionAction.ALLOW


class TestDangerousCommandsRequireConfirmation:
    """Dangerous commands should NOT be auto-allowed."""

    def test_rm(self) -> None:
        assert _eval_shell("rm -rf /tmp/data") == PermissionAction.ASK

    def test_git_push(self) -> None:
        assert _eval_shell("git push origin main") == PermissionAction.ASK

    def test_git_commit(self) -> None:
        assert _eval_shell("git commit -m 'msg'") == PermissionAction.ASK

    def test_npm_install_pkg(self) -> None:
        assert _eval_shell("npm install lodash") == PermissionAction.ASK

    def test_npm_run_arbitrary_requires_confirmation(self) -> None:
        assert _eval_shell("npm run deploy-prod") == PermissionAction.ASK

    def test_uv_run_requires_confirmation(self) -> None:
        assert _eval_shell("uv run python script.py") == PermissionAction.ASK

    def test_pip_install_editable_requires_confirmation(self) -> None:
        assert _eval_shell("pip install -e .") == PermissionAction.ASK

    def test_pip_install_pkg(self) -> None:
        assert _eval_shell("pip install requests") == PermissionAction.ASK

    def test_docker_run(self) -> None:
        assert _eval_shell("docker run ubuntu") == PermissionAction.ASK

    def test_kubectl_delete(self) -> None:
        assert _eval_shell("kubectl delete pod my-pod") == PermissionAction.ASK

    def test_cargo_publish(self) -> None:
        assert _eval_shell("cargo publish") == PermissionAction.ASK

    def test_curl(self) -> None:
        assert _eval_shell("curl https://example.com") == PermissionAction.ASK


class TestShellOperatorSplittingE2E:
    """Shell operator splitting through full pipeline."""

    def test_safe_and_safe(self) -> None:
        assert _eval_shell("ls && pwd") == PermissionAction.ALLOW

    def test_safe_and_unsafe(self) -> None:
        assert _eval_shell("ls && rm file") == PermissionAction.ASK

    def test_safe_or_safe(self) -> None:
        assert _eval_shell("ls || pwd") == PermissionAction.ALLOW

    def test_safe_or_unsafe(self) -> None:
        assert _eval_shell("ls || rm file") == PermissionAction.ASK

    def test_git_safe_and_safe(self) -> None:
        assert _eval_shell("git status && git log --oneline") == PermissionAction.ALLOW

    def test_git_safe_and_push(self) -> None:
        assert _eval_shell("git status && git push") == PermissionAction.ASK

    def test_quoted_operators_not_split(self) -> None:
        assert _eval_shell('echo "a && b"') == PermissionAction.ALLOW


class TestRedirectsBlockedE2E:
    """I/O redirects should prevent auto-allow."""

    def test_output_redirect(self) -> None:
        assert _eval_shell("echo hello > file.txt") == PermissionAction.ASK

    def test_append_redirect(self) -> None:
        assert _eval_shell("echo hello >> file.txt") == PermissionAction.ASK


class TestMixedPipelineAndOperators:
    """Complex commands mixing pipes, &&, and ||."""

    def test_pipe_then_and(self) -> None:
        assert _eval_shell("cat file | grep foo && echo found") == PermissionAction.ALLOW

    def test_triple_pipe_safe(self) -> None:
        assert _eval_shell("cat file | sort | uniq") == PermissionAction.ALLOW

    def test_git_log_pipe_grep_and_wc(self) -> None:
        assert _eval_shell("git log --oneline | grep fix && wc -l") == PermissionAction.ALLOW

    @pytest.mark.parametrize(
        "cmd",
        [
            "npm list && pip list",
            "docker ps && kubectl get pods",
            "cargo check && git status",
            "uv sync && git diff",
        ],
    )
    def test_cross_tool_safe_chains(self, cmd: str) -> None:
        assert _eval_shell(cmd) == PermissionAction.ALLOW

    @pytest.mark.parametrize(
        "cmd",
        [
            "npm list && pip install requests",
            "docker ps && docker run ubuntu",
            "git status && git push",
        ],
    )
    def test_cross_tool_mixed_chains(self, cmd: str) -> None:
        assert _eval_shell(cmd) == PermissionAction.ASK


class TestSqlGuardE2E:
    """SQL Guard integration: destructive SQL in DB clients triggers ASK even with auto-allow.

    Verifies Layer 2.5 (sql_statement_guard) integrated into shell_command_analyzer
    correctly escalates through the full evaluate_tool_call pipeline.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'DROP TABLE users'",
            "mysql -e 'DELETE FROM sessions'",
            "psql -c 'TRUNCATE TABLE logs'",
            "sqlite3 test.db 'DROP TABLE data'",
            'psql -c "ALTER TABLE users DROP COLUMN email"',
            'mysql -e "INSERT INTO admin VALUES (1, \'hacker\')"',
        ],
    )
    def test_destructive_sql_triggers_ask(self, cmd: str) -> None:
        """Destructive SQL in DB client commands must trigger ASK."""
        assert _eval_shell(cmd) == PermissionAction.ASK

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'DROP TABLE users' | psql",
            "echo 'DELETE FROM sessions' | mysql",
            "printf 'TRUNCATE TABLE logs' | psql -d mydb",
        ],
    )
    def test_pipe_destructive_sql_triggers_ask(self, cmd: str) -> None:
        """Piped destructive SQL to DB clients must trigger ASK."""
        assert _eval_shell(cmd) == PermissionAction.ASK

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'SELECT 1; DROP TABLE users'",
            "mysql -e 'BEGIN; DELETE FROM users; COMMIT'",
            "psql -c 'SELECT count(*) FROM x; TRUNCATE TABLE x'",
        ],
    )
    def test_multi_statement_bypass_blocked(self, cmd: str) -> None:
        """Multi-statement SQL injection bypass must be blocked."""
        assert _eval_shell(cmd) == PermissionAction.ASK

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'WITH x AS (SELECT 1) DELETE FROM users'",
            "mysql -e 'WITH cte AS (SELECT id FROM old) INSERT INTO archive SELECT * FROM cte'",
        ],
    )
    def test_with_cte_bypass_blocked(self, cmd: str) -> None:
        """WITH CTE wrapping destructive DML must be blocked."""
        assert _eval_shell(cmd) == PermissionAction.ASK

    def test_safe_sql_not_escalated(self) -> None:
        """Safe SQL queries (SELECT, SHOW, etc.) should NOT produce SQL escalation."""
        from myrm_agent_harness.toolkits.code_execution.security.sql_statement_guard import (
            check_sql_threats,
        )

        threats = check_sql_threats("psql -c 'SELECT * FROM users'")
        assert len(threats) == 0

    def test_auto_allow_ruleset_overridden_by_sql_guard(self) -> None:
        """Even with an explicit auto-allow rule for shell_exec, SQL Guard still blocks."""
        from myrm_agent_harness.core.security.types import PermissionRule

        auto_allow_config = SecurityConfig(
            ruleset=(PermissionRule("shell_exec", "*", PermissionAction.ALLOW),),
        )
        action, reason = evaluate_tool_call(
            "shell_exec",
            {"command": "psql -c 'DROP TABLE users'"},
            auto_allow_config,
        )
        assert action == PermissionAction.ASK
        assert "SQL" in reason or "sql" in reason.lower()

    def test_auto_allow_with_multi_statement_bypass(self) -> None:
        """Auto-allow + multi-statement SQL bypass = still blocked."""
        from myrm_agent_harness.core.security.types import PermissionRule

        auto_allow_config = SecurityConfig(
            ruleset=(PermissionRule("shell_exec", "*", PermissionAction.ALLOW),),
        )
        action, _ = evaluate_tool_call(
            "shell_exec",
            {"command": "psql -c 'SELECT 1; DROP TABLE users'"},
            auto_allow_config,
        )
        assert action == PermissionAction.ASK

    def test_auto_allow_safe_sql_passes_through(self) -> None:
        """Auto-allow + safe SQL = ALLOW (no false positive)."""
        from myrm_agent_harness.core.security.types import PermissionRule

        auto_allow_config = SecurityConfig(
            ruleset=(PermissionRule("shell_exec", "*", PermissionAction.ALLOW),),
        )
        action, _ = evaluate_tool_call(
            "shell_exec",
            {"command": "psql -c 'SELECT 1'"},
            auto_allow_config,
        )
        assert action == PermissionAction.ALLOW
