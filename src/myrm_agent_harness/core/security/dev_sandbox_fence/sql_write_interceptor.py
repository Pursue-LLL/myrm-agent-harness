"""SQL Write Operation Interceptor preventing database mutations in Dev Sandbox."""

from __future__ import annotations

import re

from .types import FenceInspectionResult, ViolationType

_MUTATING_SQL_KEYWORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create",
        "replace",
        "grant",
        "revoke",
        "merge",
        "upsert",
        "exec",
        "execute",
    }
)

_SQL_COMMENT_PATTERN = re.compile(r"(--[^\n]*|\/\*[\s\S]*?\*\/)")


class SqlWriteOperationInterceptor:
    """Inspects SQL statements and blocks all mutation commands during development execution."""

    def inspect_sql(self, sql_query: str) -> FenceInspectionResult:
        """Evaluate SQL query string. Blocks writes, updates, deletes, and DDL modifications."""
        if not sql_query or not sql_query.strip():
            return FenceInspectionResult(
                allowed=True,
                violation_type=None,
                reason="Empty SQL query",
            )

        # 1. Strip comments
        cleaned_sql = _SQL_COMMENT_PATTERN.sub(" ", sql_query).strip()

        # 2. Extract leading tokens and split into statements
        statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]

        for stmt in statements:
            tokens = stmt.split()
            if not tokens:
                continue

            first_token = tokens[0].lower()
            if first_token in _MUTATING_SQL_KEYWORDS:
                return FenceInspectionResult(
                    allowed=False,
                    violation_type=ViolationType.PROD_DB_WRITE_BLOCKED,
                    reason=f"Mutating SQL command '{first_token.upper()}' is strictly prohibited in zero-production-write dev sandbox",
                )

            # Check secondary tokens for compound commands like "SELECT ... INTO"
            lowered_stmt = stmt.lower()
            if " into " in lowered_stmt and "select " in lowered_stmt:
                return FenceInspectionResult(
                    allowed=False,
                    violation_type=ViolationType.PROD_DB_WRITE_BLOCKED,
                    reason="Mutating command 'SELECT ... INTO' is strictly prohibited in dev sandbox",
                )

        return FenceInspectionResult(
            allowed=True,
            violation_type=None,
            reason="Read-only SQL query permitted",
        )
