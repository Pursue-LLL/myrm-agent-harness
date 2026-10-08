"""Unit tests for Zero-Production-Write Dev Sandbox and Synthetic Data Fence Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.dev_sandbox_fence import (
    BranchAndDirectoryGate,
    DevExecutionMode,
    DevOperationInspection,
    DevSandboxFenceEngine,
    DevSandboxPolicy,
    SqlWriteOperationInterceptor,
    SyntheticDataFence,
    ViolationType,
)


def test_sql_write_interceptor_blocks_mutations() -> None:
    interceptor = SqlWriteOperationInterceptor()

    # 1. Mutating SQL statements blocked
    mutations = [
        "INSERT INTO patients (id, name) VALUES (1, 'Alice')",
        "UPDATE medical_records SET status='discharged' WHERE id=42",
        "DELETE FROM orders WHERE user_id = 99",
        "DROP TABLE audit_logs",
        "ALTER TABLE users ADD COLUMN is_admin boolean",
        "TRUNCATE TABLE session_store",
        "/* comment */ CREATE TABLE secret_backup (id int)",
        "SELECT * INTO new_table FROM old_table",
    ]
    for sql in mutations:
        res = interceptor.inspect_sql(sql)
        assert res.allowed is False, f"Expected {sql} to be blocked"
        assert res.violation_type == ViolationType.PROD_DB_WRITE_BLOCKED

    # 2. Read-only SQL statements allowed
    queries = [
        "SELECT * FROM patients WHERE id = 1",
        "EXPLAIN SELECT count(*) FROM records",
        "SHOW TABLES",
        "DESCRIBE users",
        "-- comment\nSELECT id, name FROM doctors",
    ]
    for sql in queries:
        res = interceptor.inspect_sql(sql)
        assert res.allowed is True, f"Expected {sql} to be allowed"
        assert res.violation_type is None


def test_synthetic_data_fence_substitutes_prod_database() -> None:
    fence = SyntheticDataFence(load_defaults=True)

    # 1. Real production Postgres URI is intercepted and substituted
    prod_uri = "postgresql://prod-ehr-cluster.internal:5432/clinical_data"
    res_sub = fence.inspect_db_connection(prod_uri, enforce_synthetic=True)
    assert res_sub.allowed is True
    assert res_sub.violation_type == ViolationType.PROD_CREDENTIAL_SUBSTITUTION
    assert res_sub.substituted_target == "mock://dev-synthetic-postgres-replica:5432/test_db"
    assert "synthetic fixture" in res_sub.reason

    # 2. Direct memory fixture allowed as-is
    mem_uri = "sqlite:///:memory:"
    res_mem = fence.inspect_db_connection(mem_uri, enforce_synthetic=True)
    assert res_mem.allowed is True
    assert res_mem.substituted_target == mem_uri


def test_branch_gate_blocks_production_branches() -> None:
    gate = BranchAndDirectoryGate()
    policy = DevSandboxPolicy()

    # Blocked production branches
    assert gate.inspect_git_branch("main", policy).allowed is False
    assert gate.inspect_git_branch("master", policy).allowed is False
    assert gate.inspect_git_branch("production", policy).allowed is False
    assert gate.inspect_git_branch("release/v2.1", policy).allowed is False

    # Allowed dev isolated branches
    res_dev1 = gate.inspect_git_branch("agent/dev-fhir-adapter", policy)
    assert res_dev1.allowed is True

    res_dev2 = gate.inspect_git_branch("feature/new-validator", policy)
    assert res_dev2.allowed is True


def test_directory_gate_restricts_writes() -> None:
    gate = BranchAndDirectoryGate()
    policy = DevSandboxPolicy()

    # 1. Allowed writes within dev directories
    assert gate.inspect_file_write("src/adapters/emr_adapter.py", policy).allowed is True
    assert gate.inspect_file_write("tests/unit/test_emr.py", policy).allowed is True
    assert gate.inspect_file_write("mock/fixtures.json", policy).allowed is True
    assert gate.inspect_file_write("sandbox/scratch.py", policy).allowed is True

    # 2. Blocked writes to production sensitive patterns
    res_wf = gate.inspect_file_write(".github/workflows/deploy.yml", policy)
    assert res_wf.allowed is False
    assert res_wf.violation_type == ViolationType.SENSITIVE_DIR_WRITE_BLOCKED

    res_k8s = gate.inspect_file_write("deploy/k8s/values.production.yaml", policy)
    assert res_k8s.allowed is False

    res_env = gate.inspect_file_write(".env.production", policy)
    assert res_env.allowed is False

    # 3. Blocked writes outside authorized directories
    res_core = gate.inspect_file_write("src/core/security_kernel.py", policy)
    assert res_core.allowed is False
    assert "outside authorized dev directories" in res_core.reason


def test_dev_sandbox_fence_engine_end_to_end_and_alerts() -> None:
    engine = DevSandboxFenceEngine()
    session_id = "dev-session-audit-1"

    # Mutating SQL blocked
    sql_op = DevOperationInspection(
        operation_type="sql",
        target="users",
        payload="DELETE FROM users WHERE id = 10",
        session_id=session_id,
    )
    res_sql = engine.inspect_operation(sql_op)
    assert res_sql.allowed is False

    # Main branch push blocked
    branch_op = DevOperationInspection(
        operation_type="git_branch",
        target="main",
        session_id=session_id,
    )
    res_branch = engine.inspect_operation(branch_op)
    assert res_branch.allowed is False

    # Check alerts captured
    alerts = engine.get_alerts(session_id)
    assert len(alerts) == 2
    assert alerts[0].violation_type == ViolationType.PROD_DB_WRITE_BLOCKED
    assert alerts[1].violation_type == ViolationType.PROD_BRANCH_PUSH_BLOCKED

    # Test production controlled mode bypass
    engine.mode = DevExecutionMode.PRODUCTION_CONTROLLED
    res_bypassed = engine.inspect_operation(sql_op)
    assert res_bypassed.allowed is True
    assert "bypassed" in res_bypassed.reason
