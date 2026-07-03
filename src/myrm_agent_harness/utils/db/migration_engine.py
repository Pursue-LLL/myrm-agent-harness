"""Zero-Ops Stateful SQLite Migration Engine.

Provides a lightweight SQLite migration utility (no Alembic).
SQLAlchemy AsyncEngine is optional at import time; install `sqlalchemy` when using StatefulMigrationEngine.

[INPUT]
- sqlalchemy (optional)::text, AsyncEngine — lazy import at runtime

[OUTPUT]
- StatefulMigrationEngine: Zero-ops SQLite migration engine with state tracking
- MigrationStatement: Versioned SQL migration statement
- MigrationReport: Migration execution detailed report

[POS]
Zero-ops stateful SQLite migration engine. Provides version tracking, precise timing,
checksum verification, and baseline initialization for Agent-in-Sandbox architectures.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_SQLALCHEMY_INSTALL_HINT = (
    "sqlalchemy is required for StatefulMigrationEngine. "
    "Install with: pip install sqlalchemy  # or uv sync --group dev"
)


def _sql_text(sql: str) -> object:
    try:
        from sqlalchemy import text
    except ImportError as exc:
        raise ImportError(_SQLALCHEMY_INSTALL_HINT) from exc
    return text(sql)


_IDEMPOTENT_ERROR_FRAGMENTS: tuple[str, ...] = (
    "duplicate column name",
    "already exists",
    "index already exists",
    "table .* already exists",
    "no such column",
)


def _is_idempotent_skip(error_message: str) -> bool:
    """Detect idempotent SQLite errors safe to skip when state was lost.

    Triggers when a CREATE / ALTER statement was already applied out-of-band
    (parallel migration runs, baseline drift, manual hotfixes) but the
    `_schema_migrations` table missed the bookkeeping. Without this guard a
    perfectly migrated schema would refuse to boot.
    """
    lower = error_message.lower()
    return any(fragment in lower for fragment in _IDEMPOTENT_ERROR_FRAGMENTS)


@dataclass(frozen=True, slots=True)
class MigrationStatement:
    """A single versioned SQL migration statement."""

    version: int
    sql: str


@dataclass
class MigrationReport:
    """Detailed report of a migration run."""

    applied_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    total_duration_ms: float = 0.0
    slowest_migrations: list[tuple[int, str, float]] = field(default_factory=list)
    error_message: str | None = None
    failed_sql: str | None = None
    failed_version: int | None = None
    baselined: bool = False


class StatefulMigrationEngine:
    """Stateful migration engine for SQLite databases.

    Args:
        engine: The SQLAlchemy AsyncEngine.
        table_name: The name of the state table (default: _schema_migrations).
        baseline_check_sql: SQL to check if the database is already populated
            (e.g., "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").
            If provided and the state table is missing but this check passes,
            all migrations will be marked as "baselined" (applied) without execution.
        slow_threshold_ms: Migrations taking longer than this will be recorded in slowest_migrations.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        table_name: str = "_schema_migrations",
        baseline_check_sql: str | None = None,
        slow_threshold_ms: float = 100.0,
    ):
        self.engine = engine
        self.table_name = table_name
        self.baseline_check_sql = baseline_check_sql
        self.slow_threshold_ms = slow_threshold_ms

    def _compute_checksum(self, sql: str) -> str:
        """Compute SHA-256 checksum of the SQL statement."""
        return hashlib.sha256(sql.encode("utf-8")).hexdigest()

    async def _init_state_table(self) -> bool:
        """Create the state table if it doesn't exist. Returns True if newly created."""
        check_sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
        async with self.engine.connect() as conn:
            result = await conn.execute(_sql_text(check_sql), {"name": self.table_name})
            exists = result.scalar() is not None

        if not exists:
            create_sql = f"""
            CREATE TABLE {self.table_name} (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_ms REAL NOT NULL,
                checksum VARCHAR(64) NOT NULL
            )
            """
            async with self.engine.begin() as conn:
                await conn.execute(_sql_text(create_sql))
            return True
        return False

    async def _needs_baseline(self) -> bool:
        """Check if the database is already populated and needs baselining."""
        if not self.baseline_check_sql:
            return False
        try:
            async with self.engine.connect() as conn:
                result = await conn.execute(_sql_text(self.baseline_check_sql))
                return result.scalar() is not None
        except Exception as exc:
            logger.debug("Baseline check failed: %s", exc)
            return False

    async def run_migrations(self, migrations: list[MigrationStatement]) -> MigrationReport:
        """Execute pending migrations sequentially."""
        report = MigrationReport()
        total_start = time.time()

        newly_created = await self._init_state_table()

        # Handle Baseline for existing databases
        if newly_created and await self._needs_baseline():
            logger.info("Existing database detected. Baselining migrations...")
            async with self.engine.begin() as conn:
                for m in migrations:
                    checksum = self._compute_checksum(m.sql)
                    insert_sql = f"""
                    INSERT INTO {self.table_name} (version, duration_ms, checksum)
                    VALUES (:version, 0, :checksum)
                    """
                    await conn.execute(
                        _sql_text(insert_sql),
                        {"version": m.version, "checksum": "baselined:" + checksum},
                    )
            report.skipped_count = len(migrations)
            report.baselined = True
            report.total_duration_ms = (time.time() - total_start) * 1000
            return report

        # Fetch already applied migrations
        applied_versions: dict[int, str] = {}
        async with self.engine.connect() as conn:
            result = await conn.execute(_sql_text(f"SELECT version, checksum FROM {self.table_name}"))
            for row in result:
                applied_versions[row[0]] = row[1]

        # Execute pending migrations
        for m in migrations:
            if m.version in applied_versions:
                # Verify checksum to prevent tampering
                existing_checksum = applied_versions[m.version]
                if not existing_checksum.startswith("baselined:"):
                    expected_checksum = self._compute_checksum(m.sql)
                    if existing_checksum != expected_checksum:
                        msg = (
                            f"Migration V{m.version} has been modified after being applied. "
                            f"This is a critical error. Never modify past migrations. "
                            f"Expected checksum: {expected_checksum}, found: {existing_checksum}"
                        )
                        logger.warning(msg)
                report.skipped_count += 1
                continue

            start_time = time.time()
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(_sql_text(m.sql))
                    duration_ms = (time.time() - start_time) * 1000
                    checksum = self._compute_checksum(m.sql)
                    insert_sql = f"""
                    INSERT INTO {self.table_name} (version, duration_ms, checksum)
                    VALUES (:version, :duration_ms, :checksum)
                    """
                    await conn.execute(
                        _sql_text(insert_sql),
                        {"version": m.version, "duration_ms": duration_ms, "checksum": checksum},
                    )

                report.applied_count += 1
                if duration_ms > self.slow_threshold_ms:
                    report.slowest_migrations.append((m.version, m.sql, duration_ms))

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                if _is_idempotent_skip(str(e)):
                    logger.info(
                        "Migration V%d idempotent skip (%s): %s",
                        m.version,
                        type(e).__name__,
                        str(e).splitlines()[0][:120],
                    )
                    async with self.engine.begin() as conn:
                        checksum = self._compute_checksum(m.sql)
                        insert_sql = f"""
                        INSERT INTO {self.table_name} (version, duration_ms, checksum)
                        VALUES (:version, :duration_ms, :checksum)
                        """
                        await conn.execute(
                            _sql_text(insert_sql),
                            {
                                "version": m.version,
                                "duration_ms": duration_ms,
                                "checksum": "idempotent:" + checksum,
                            },
                        )
                    report.skipped_count += 1
                    continue

                report.failed_count = 1
                report.error_message = str(e)
                report.failed_sql = m.sql
                report.failed_version = m.version
                break

        report.total_duration_ms = (time.time() - total_start) * 1000
        report.slowest_migrations.sort(key=lambda x: x[2], reverse=True)
        return report
