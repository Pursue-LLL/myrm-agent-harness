"""Tests for SQL Statement Guard — destructive SQL detection in DB client commands."""

import pytest

from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    ThreatLevel,
    analyze_command,
    has_escalate_threat,
)
from myrm_agent_harness.toolkits.code_execution.security.sql_statement_guard import (
    check_sql_threats,
)


class TestDirectSQLFlag:
    """Test SQL extraction from DB client -c/-e/--eval flags."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'DROP TABLE users'",
            "psql --command 'DROP TABLE users'",
            "psql -h localhost -c 'DROP TABLE users'",
            "mysql -e 'DROP TABLE users'",
            "mysql --execute 'DROP TABLE users'",
            "mariadb -e 'DELETE FROM orders'",
            "sqlcmd -Q 'TRUNCATE TABLE logs'",
            "mongosh --eval 'db.users.drop()'",
        ],
    )
    def test_destructive_sql_detected(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) >= 1
        assert threats[0].level == ThreatLevel.ESCALATE
        assert threats[0].category == "destructive_sql"

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'SELECT * FROM users'",
            "psql -c 'SHOW tables'",
            "mysql -e 'EXPLAIN SELECT 1'",
            "sqlite3 app.db 'SELECT count(*) FROM orders'",
            "psql -c 'PRAGMA table_info(users)'",
            "psql -c 'BEGIN'",
            "mysql -e 'SET search_path = public'",
        ],
    )
    def test_safe_sql_not_flagged(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) == 0

    def test_sqlite3_positional_destructive(self) -> None:
        threats = check_sql_threats("sqlite3 app.db 'DROP TABLE sessions'")
        assert len(threats) == 1
        assert threats[0].level == ThreatLevel.ESCALATE

    def test_sqlite3_positional_safe(self) -> None:
        threats = check_sql_threats("sqlite3 app.db 'SELECT * FROM sessions'")
        assert len(threats) == 0


class TestPipeToDBClient:
    """Test SQL extraction from pipe-to-DB-client patterns."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'DROP TABLE users' | psql",
            "echo 'DELETE FROM orders' | mysql",
            "printf 'TRUNCATE TABLE logs' | sqlite3 app.db",
            "echo 'ALTER TABLE users ADD COLUMN age int' | psql -h db.host",
        ],
    )
    def test_pipe_destructive_detected(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) >= 1
        assert threats[0].level == ThreatLevel.ESCALATE

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'SELECT 1' | psql",
            "echo 'SHOW DATABASES' | mysql",
            "printf 'PRAGMA table_info(x)' | sqlite3 test.db",
        ],
    )
    def test_pipe_safe_not_flagged(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) == 0

    def test_cat_pipe_not_flagged(self) -> None:
        """cat file | psql — file content unknown, cannot analyze."""
        threats = check_sql_threats("cat migrations.sql | psql")
        assert len(threats) == 0


class TestNonDBCommands:
    """Verify zero false positives on non-DB commands."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls -la",
            "echo 'hello world'",
            "grep 'DROP' logfile.txt",
            "npm install",
            "python3 script.py",
            "git status",
            "curl http://example.com",
        ],
    )
    def test_non_db_commands_clean(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) == 0


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_command(self) -> None:
        assert check_sql_threats("") == []
        assert check_sql_threats("   ") == []

    def test_empty_sql_in_quotes(self) -> None:
        threats = check_sql_threats("psql -c ''")
        assert len(threats) == 0

    def test_sql_with_comments(self) -> None:
        threats = check_sql_threats("psql -c '-- comment\nDROP TABLE users'")
        assert len(threats) >= 1

    def test_multiple_destructive_statements(self) -> None:
        cmd = "psql -c 'DROP TABLE a' -c 'DROP TABLE b'"
        threats = check_sql_threats(cmd)
        assert len(threats) >= 1

    def test_unknown_sql_keyword_escalated(self) -> None:
        """Unknown first keyword should be escalated (conservative)."""
        threats = check_sql_threats("psql -c 'VACUUM'")
        assert len(threats) >= 1
        assert threats[0].level == ThreatLevel.ESCALATE

    def test_with_keyword_safe(self) -> None:
        threats = check_sql_threats("psql -c 'WITH cte AS (SELECT 1) SELECT * FROM cte'")
        assert len(threats) == 0

    def test_full_path_db_client(self) -> None:
        threats = check_sql_threats("/usr/bin/psql -c 'DROP TABLE users'")
        assert len(threats) >= 1

    def test_double_quoted_destructive(self) -> None:
        """Double-quoted SQL must also be detected."""
        threats = check_sql_threats('psql -c "DROP TABLE users"')
        assert len(threats) >= 1
        assert threats[0].level == ThreatLevel.ESCALATE

    def test_double_quoted_safe(self) -> None:
        threats = check_sql_threats('psql -c "SELECT 1"')
        assert len(threats) == 0

    def test_double_quoted_pipe(self) -> None:
        threats = check_sql_threats('echo "INSERT INTO x VALUES (1)" | psql')
        assert len(threats) >= 1


class TestMultiStatementBypass:
    """Verify multi-statement injection is detected."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'SELECT 1; DROP TABLE users'",
            "mysql -e 'SELECT count(*) FROM x; TRUNCATE TABLE x'",
            "psql -c 'BEGIN; DELETE FROM users; COMMIT'",
            "psql -c 'SELECT 1; INSERT INTO logs VALUES (1)'",
        ],
    )
    def test_multi_statement_destructive(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) >= 1
        assert threats[0].level == ThreatLevel.ESCALATE

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'SELECT 1; SELECT 2'",
            "psql -c 'BEGIN; SELECT 1; COMMIT'",
            "mysql -e 'SET search_path = public; SHOW tables'",
        ],
    )
    def test_multi_statement_safe(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) == 0


class TestWithCTEBypass:
    """Verify WITH CTE wrapping destructive DML is detected."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'WITH x AS (SELECT 1) DELETE FROM users'",
            "psql -c 'WITH cte AS (SELECT id FROM old) INSERT INTO archive SELECT * FROM cte'",
            "mysql -e 'WITH t AS (SELECT 1) UPDATE users SET active=0'",
        ],
    )
    def test_with_cte_destructive(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) >= 1
        assert threats[0].level == ThreatLevel.ESCALATE

    @pytest.mark.parametrize(
        "cmd",
        [
            "psql -c 'WITH x AS (SELECT 1) SELECT * FROM x'",
            "psql -c 'WITH cte AS (SELECT count(*) FROM users) SELECT * FROM cte'",
        ],
    )
    def test_with_cte_safe(self, cmd: str) -> None:
        threats = check_sql_threats(cmd)
        assert len(threats) == 0


class TestIntegrationWithAnalyzeCommand:
    """Verify integration with shell_command_analyzer.analyze_command()."""

    def test_previously_bypassed_now_detected(self) -> None:
        """The original vulnerability: SQL in single quotes was undetected."""
        threats = analyze_command("psql -c 'DROP TABLE users'")
        escalate = [t for t in threats if t.level == ThreatLevel.ESCALATE]
        assert len(escalate) >= 1
        assert any("SQL" in t.detail or "sql" in t.detail.lower() for t in escalate)

    def test_has_escalate_threat_helper(self) -> None:
        threat = has_escalate_threat("mysql -e 'DELETE FROM users'")
        assert threat is not None
        assert threat.category == "destructive_sql"

    def test_safe_sql_no_escalate(self) -> None:
        threat = has_escalate_threat("psql -c 'SELECT 1'")
        # Should not trigger SQL escalation (may have other escalations)
        threats = analyze_command("psql -c 'SELECT 1'")
        sql_threats = [t for t in threats if t.category == "destructive_sql"]
        assert len(sql_threats) == 0

    def test_pipe_now_detected(self) -> None:
        """Pipe scenario was also vulnerable."""
        threats = analyze_command("echo 'DROP TABLE users' | psql")
        sql_threats = [t for t in threats if t.category == "destructive_sql"]
        assert len(sql_threats) >= 1

    def test_normal_commands_unaffected(self) -> None:
        """Ensure no regression on normal commands."""
        assert analyze_command("ls -la") == ()
        assert analyze_command("git status") == ()
        assert analyze_command("echo hello") == ()
