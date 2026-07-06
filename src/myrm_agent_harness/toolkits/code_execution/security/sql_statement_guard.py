"""SQL Statement Guard — detect destructive SQL in DB client commands.

Extracts SQL statements from database client commands (psql, mysql, sqlite3,
etc.) and flags write/destructive operations as ESCALATE threats, forcing
human approval even when shell_exec is auto-allowed.

Two extraction modes:
1. Direct SQL parameter: ``psql -c 'DROP TABLE users'``
2. Pipe to DB client: ``echo 'DROP TABLE users' | psql``

Design:
- Runs on the ORIGINAL command (before quote stripping) because SQL resides
  inside single quotes which ``_strip_quoted_content`` replaces with placeholders.
- Returns ESCALATE (not BLOCK) so users can approve legitimate destructive ops.
- Only triggers for known DB client executables — zero false positives on
  unrelated commands.

[INPUT]
- shell_command_analyzer::CommandThreat, ThreatLevel (POS: Shell Command Analyzer — unified security analysis for shell commands.)

[OUTPUT]
- check_sql_threats: Detect destructive SQL in DB client shell commands.

[POS]
SQL Statement Guard — detect destructive SQL in DB client commands.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    CommandThreat,
    ThreatLevel,
)

# DB client executables and their SQL-carrying flags.
# Empty tuple means SQL is a positional argument (e.g. sqlite3 db 'SQL').
_DB_CLIENT_SQL_FLAGS: dict[str, tuple[str, ...]] = {
    "psql": ("-c", "--command"),
    "mysql": ("-e", "--execute"),
    "mariadb": ("-e", "--execute"),
    "sqlite3": (),
    "sqlcmd": ("-Q", "-q", "--query"),
    "mongosh": ("--eval",),
    "mongo": ("--eval",),
}

# Safe read-only SQL keywords (whitelist). Anything NOT in this set triggers
# ESCALATE — conservative by design (unknown operations require human approval).
_SAFE_SQL_KEYWORDS: frozenset[str] = frozenset({
    "SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC",
    "PRAGMA", "WITH", "VALUES",
    "SET", "BEGIN", "COMMIT", "ROLLBACK",
})

# Regex to extract content from quoted strings.
_SINGLE_QUOTED_RE = re.compile(r"'([^']*)'")
_DOUBLE_QUOTED_RE = re.compile(r'"([^"]*)"')

# Regex to detect pipe target: last segment after |
_PIPE_SPLIT_RE = re.compile(r"\|(?![|])")


def _extract_first_sql_keyword(sql: str) -> str | None:
    """Extract the first meaningful keyword from a SQL statement.

    Skips leading whitespace, single-line comments (--), and block comments.
    """
    text = sql.strip()

    # Skip leading comments
    while text:
        if text.startswith("--"):
            newline = text.find("\n")
            if newline == -1:
                return None
            text = text[newline + 1:].strip()
        elif text.startswith("/*"):
            end = text.find("*/")
            if end == -1:
                return None
            text = text[end + 2:].strip()
        else:
            break

    if not text:
        return None

    # Extract first word
    match = re.match(r"[A-Za-z_]+", text)
    return match.group(0).upper() if match else None


def _is_destructive_sql(sql: str) -> bool:
    """Return True if the SQL statement begins with a destructive keyword.

    Conservative policy: unknown keywords (not in safe or destructive sets) are
    treated as destructive to force human review.
    """
    keyword = _extract_first_sql_keyword(sql)
    if not keyword:
        return False
    if keyword in _SAFE_SQL_KEYWORDS:
        return False
    # Anything not explicitly safe (including unknown keywords) is destructive
    return True


def _get_base_command(token: str) -> str:
    """Extract base command name from a path (e.g. /usr/bin/psql -> psql)."""
    return token.rsplit("/", 1)[-1]


def _extract_sql_from_flag_args(command: str) -> list[str]:
    """Extract SQL from DB client commands using -c/-e/--eval flags or positional args."""
    sqls: list[str] = []
    tokens = command.split()
    if not tokens:
        return sqls

    base_cmd = _get_base_command(tokens[0])
    flags = _DB_CLIENT_SQL_FLAGS.get(base_cmd)
    if flags is None:
        return sqls

    if flags:
        # Flag-based extraction: find -c/-e/--eval followed by quoted content
        for flag in flags:
            escaped = re.escape(flag)
            for quote_re in (
                re.compile(escaped + r"""\s+'([^']*)'"""),
                re.compile(escaped + r'''\s+"([^"]*)"'''),
            ):
                for match in quote_re.finditer(command):
                    sqls.append(match.group(1))
    else:
        # Positional: sqlite3 <db_file> '<SQL>' or "<SQL>"
        for regex in (_SINGLE_QUOTED_RE, _DOUBLE_QUOTED_RE):
            quoted_matches = list(regex.finditer(command))
            if quoted_matches:
                sqls.append(quoted_matches[-1].group(1))
                break

    return sqls


def _extract_sql_from_pipe(command: str) -> list[str]:
    """Extract SQL from pipe-to-DB-client patterns (echo 'SQL' | psql)."""
    sqls: list[str] = []
    segments = _PIPE_SPLIT_RE.split(command)
    if len(segments) < 2:
        return sqls

    # Check if the last segment's base command is a DB client
    last_segment = segments[-1].strip()
    last_tokens = last_segment.split()
    if not last_tokens:
        return sqls

    last_base = _get_base_command(last_tokens[0])
    if last_base not in _DB_CLIENT_SQL_FLAGS:
        return sqls

    # Extract SQL from preceding segments' quoted content
    for segment in segments[:-1]:
        segment_stripped = segment.strip()
        tokens = segment_stripped.split()
        if not tokens:
            continue
        base = _get_base_command(tokens[0])
        if base in ("echo", "printf", "cat"):
            for regex in (_SINGLE_QUOTED_RE, _DOUBLE_QUOTED_RE):
                for match in regex.finditer(segment_stripped):
                    sqls.append(match.group(1))

    return sqls


def check_sql_threats(command: str) -> list[CommandThreat]:
    """Detect destructive SQL in database client shell commands.

    Checks two patterns:
    1. DB client with SQL flag: ``psql -c 'DROP TABLE users'``
    2. Pipe to DB client: ``echo 'DROP TABLE users' | psql``

    Returns ESCALATE-level threats for destructive SQL operations.
    Pure function — no side effects, no I/O.
    """
    if not command or not command.strip():
        return []

    threats: list[CommandThreat] = []
    sql_statements: list[str] = []

    # Mode 1: Direct SQL parameter
    sql_statements.extend(_extract_sql_from_flag_args(command))

    # Mode 2: Pipe to DB client
    sql_statements.extend(_extract_sql_from_pipe(command))

    for sql in sql_statements:
        if not sql.strip():
            continue
        if _is_destructive_sql(sql):
            keyword = _extract_first_sql_keyword(sql)
            threats.append(CommandThreat(
                level=ThreatLevel.ESCALATE,
                category="destructive_sql",
                detail=f"Destructive SQL operation: {keyword}",
                evidence=sql[:80],
            ))

    return threats
