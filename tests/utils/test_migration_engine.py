import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from myrm_agent_harness.utils.db.migration_engine import MigrationStatement, StatefulMigrationEngine


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_engine_fresh_install(engine):
    engine_runner = StatefulMigrationEngine(engine)

    migrations = [
        MigrationStatement(version=0, sql="CREATE TABLE test1 (id INTEGER PRIMARY KEY)"),
        MigrationStatement(version=1, sql="CREATE TABLE test2 (id INTEGER PRIMARY KEY)"),
    ]

    report = await engine_runner.run_migrations(migrations)

    assert report.applied_count == 2
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert not report.baselined

    # Verify tables exist
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in res}
        assert "test1" in tables
        assert "test2" in tables
        assert "_schema_migrations" in tables


@pytest.mark.asyncio
async def test_migration_engine_baseline(engine):
    # Simulate an existing database without the state table
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))

    engine_runner = StatefulMigrationEngine(
        engine, baseline_check_sql="SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    )

    migrations = [
        MigrationStatement(version=0, sql="CREATE TABLE users (id INTEGER PRIMARY KEY)"),  # This would fail if executed
        MigrationStatement(version=1, sql="ALTER TABLE users ADD COLUMN name TEXT"),
    ]

    report = await engine_runner.run_migrations(migrations)

    assert report.applied_count == 0
    assert report.skipped_count == 2
    assert report.failed_count == 0
    assert report.baselined

    # Verify state table was created and populated
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT version, checksum FROM _schema_migrations"))
        rows = list(res)
        assert len(rows) == 2
        assert rows[0][0] == 0
        assert rows[0][1].startswith("baselined:")
        assert rows[1][0] == 1
        assert rows[1][1].startswith("baselined:")


@pytest.mark.asyncio
async def test_migration_engine_failure(engine):
    engine_runner = StatefulMigrationEngine(engine)

    migrations = [
        MigrationStatement(version=0, sql="CREATE TABLE test1 (id INTEGER PRIMARY KEY)"),
        MigrationStatement(version=1, sql="INVALID SQL SYNTAX"),
        MigrationStatement(version=2, sql="CREATE TABLE test2 (id INTEGER PRIMARY KEY)"),
    ]

    report = await engine_runner.run_migrations(migrations)

    assert report.applied_count == 1
    assert report.failed_count == 1
    assert report.failed_version == 1
    assert "syntax error" in report.error_message.lower()

    # Verify state table only has version 0
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT version FROM _schema_migrations"))
        rows = list(res)
        assert len(rows) == 1
        assert rows[0][0] == 0


@pytest.mark.asyncio
async def test_migration_engine_checksum_tampering(engine):
    engine_runner = StatefulMigrationEngine(engine)

    migrations_v1 = [
        MigrationStatement(version=0, sql="CREATE TABLE test1 (id INTEGER PRIMARY KEY)"),
    ]

    # First run: apply migration V0
    report = await engine_runner.run_migrations(migrations_v1)
    assert report.applied_count == 1

    # Second run: modify the SQL of V0 (tampering)
    migrations_v2 = [
        MigrationStatement(version=0, sql="CREATE TABLE test1 (id INTEGER PRIMARY KEY, name TEXT)"),
    ]

    report = await engine_runner.run_migrations(migrations_v2)
    assert report.skipped_count == 1, "Tampered migration should be skipped (warning-only)"


@pytest.mark.asyncio
async def test_migration_engine_idempotent_skip_duplicate_column(engine):
    """ALTER TABLE ADD COLUMN whose target column already exists must not abort boot.

    Reproduces the production failure where parallel sandbox sessions mutate the
    schema out-of-band, leaving `_schema_migrations` short of a bookkeeping row.
    The engine must record the migration as idempotently skipped instead of
    raising RuntimeError.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE agents (id INTEGER PRIMARY KEY, name TEXT)"))

    engine_runner = StatefulMigrationEngine(engine)

    migrations = [
        MigrationStatement(version=0, sql="CREATE TABLE IF NOT EXISTS agents (id INTEGER PRIMARY KEY)"),
        MigrationStatement(version=1, sql="ALTER TABLE agents ADD COLUMN name TEXT"),
        MigrationStatement(version=2, sql="ALTER TABLE agents ADD COLUMN created_at TIMESTAMP"),
    ]

    report = await engine_runner.run_migrations(migrations)

    assert report.failed_count == 0, f"Idempotent error must not fail: {report.error_message}"
    assert report.applied_count == 2, "V0 (IF NOT EXISTS) and V2 (new column) succeed"
    assert report.skipped_count == 1, "V1 (ALTER duplicate column) idempotently skipped"

    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT version, checksum FROM _schema_migrations ORDER BY version"))
        rows = list(res)
        assert {r[0] for r in rows} == {0, 1, 2}
        idempotent_marks = [r[1] for r in rows if r[1].startswith("idempotent:")]
        assert len(idempotent_marks) == 1, "Only V1 should be flagged idempotent"


@pytest.mark.asyncio
async def test_migration_engine_idempotent_skip_index_already_exists(engine):
    """CREATE INDEX whose target already exists must skip without aborting."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE chats (id INTEGER PRIMARY KEY, status TEXT)"))
        await conn.execute(text("CREATE INDEX idx_chats_status ON chats(status)"))

    engine_runner = StatefulMigrationEngine(engine)

    migrations = [
        MigrationStatement(version=0, sql="CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY)"),
        MigrationStatement(version=1, sql="CREATE INDEX idx_chats_status ON chats(status)"),
    ]

    report = await engine_runner.run_migrations(migrations)

    assert report.failed_count == 0
    assert report.applied_count == 1, "V0 (IF NOT EXISTS) succeeds without error"
    assert report.skipped_count == 1, "V1 (CREATE INDEX duplicate) idempotently skipped"


@pytest.mark.asyncio
async def test_migration_engine_idempotent_skip_drop_nonexistent_column(engine):
    """DROP COLUMN targeting a nonexistent column must skip without aborting.

    Reproduces the production failure where artifacts table never had
    deployment_url but a migration tries to drop it.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE artifacts (id INTEGER PRIMARY KEY, name TEXT)"))

    engine_runner = StatefulMigrationEngine(engine)

    migrations = [
        MigrationStatement(version=0, sql="CREATE TABLE IF NOT EXISTS artifacts (id INTEGER PRIMARY KEY)"),
        MigrationStatement(version=1, sql="ALTER TABLE artifacts DROP COLUMN nonexistent_col"),
        MigrationStatement(version=2, sql="ALTER TABLE artifacts ADD COLUMN description TEXT"),
    ]

    report = await engine_runner.run_migrations(migrations)

    assert report.failed_count == 0, f"DROP nonexistent column must not fail: {report.error_message}"
    assert report.applied_count == 2, "V0 and V2 succeed"
    assert report.skipped_count == 1, "V1 (DROP nonexistent column) idempotently skipped"

    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT version, checksum FROM _schema_migrations ORDER BY version"))
        rows = list(res)
        assert {r[0] for r in rows} == {0, 1, 2}
        idempotent_marks = [r[1] for r in rows if r[1].startswith("idempotent:")]
        assert len(idempotent_marks) == 1, "Only V1 should be flagged idempotent"
