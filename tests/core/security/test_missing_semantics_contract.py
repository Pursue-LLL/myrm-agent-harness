"""Unit tests for missing_semantics.py and safe_exec fail-closed gate."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.missing_semantics import (
    MissingDependencyFailClosedError,
    MissingDependencyFailFastError,
    MissingSemanticsContract,
    MissingSemanticsPolicy,
    enforce_missing_semantics,
    get_registered_contract,
    list_registered_contracts,
)
from myrm_agent_harness.core.security.safe_exec import safe_exec


class TestMissingSemanticsContract:
    """Test registry and contract declarations."""

    def test_registered_contracts_exist(self) -> None:
        contracts = list_registered_contracts()
        assert len(contracts) >= 6

        sandbox_contract = get_registered_contract("sandbox")
        assert sandbox_contract is not None
        assert sandbox_contract.policy == MissingSemanticsPolicy.FAIL_CLOSED
        assert "sandbox" in (sandbox_contract.description or "").lower()

        vault_contract = get_registered_contract("credential_vault")
        assert vault_contract is not None
        assert vault_contract.policy == MissingSemanticsPolicy.FAIL_CLOSED

        db_contract = get_registered_contract("primary_database")
        assert db_contract is not None
        assert db_contract.policy == MissingSemanticsPolicy.FAIL_FAST

        vision_contract = get_registered_contract("vision_multimodal")
        assert vision_contract is not None
        assert vision_contract.policy == MissingSemanticsPolicy.FALLBACK

    def test_dynamic_register_and_lookup(self) -> None:
        from myrm_agent_harness.core.security.missing_semantics import (
            register_missing_semantics_contract,
        )

        custom = MissingSemanticsContract(
            category="custom_gpu_cluster",
            policy=MissingSemanticsPolicy.FAIL_CLOSED,
            error_code="ERR_MISSING_GPU_CLUSTER",
            user_message="GPU inference cluster is unreachable",
            remediation_hint="Verify remote GPU cluster endpoint.",
            description="High-throughput GPU inference pool",
        )
        register_missing_semantics_contract(custom)

        retrieved = get_registered_contract("custom_gpu_cluster")
        assert retrieved is not None
        assert retrieved.error_code == "ERR_MISSING_GPU_CLUSTER"
        assert retrieved.policy == MissingSemanticsPolicy.FAIL_CLOSED


class TestDiagnosticSerialization:
    """Test to_diagnostic_dict export on MissingSemanticsError hierarchy."""

    def test_fail_closed_error_diagnostic_dict(self) -> None:
        err = MissingDependencyFailClosedError(
            component_name="sandbox",
            action="execute_shell",
            repair_hint="Start docker daemon",
            details="Docker socket /var/run/docker.sock not found",
            error_code="ERR_MISSING_SANDBOX",
        )
        diag = err.to_diagnostic_dict()
        assert diag["error_code"] == "ERR_MISSING_SANDBOX"
        assert diag["policy"] == "fail_closed"
        assert diag["component_name"] == "sandbox"
        assert diag["action"] == "execute_shell"
        assert diag["repair_hint"] == "Start docker daemon"
        assert "docker.sock" in diag["details"]

    def test_fail_fast_error_diagnostic_dict(self) -> None:
        err = MissingDependencyFailFastError(
            component_name="core_postgres",
            action="boot_migration",
            repair_hint="Verify DATABASE_URL",
            details="Connection refused: 5432",
        )
        diag = err.to_diagnostic_dict()
        assert diag["policy"] == "fail_fast"
        assert diag["component_name"] == "core_postgres"
        assert diag["action"] == "boot_migration"
        assert diag["repair_hint"] == "Verify DATABASE_URL"


class TestEnforceMissingSemanticsDecorator:
    """Test @enforce_missing_semantics on sync and async functions."""

    def test_sync_fail_closed_raises_error(self) -> None:
        @enforce_missing_semantics(
            MissingSemanticsPolicy.FAIL_CLOSED,
            "sandbox",
            guard_fn=lambda: False,
            repair_hint="Start docker daemon",
        )
        def run_isolated_task() -> str:
            return "executed"

        with pytest.raises(MissingDependencyFailClosedError) as exc_info:
            run_isolated_task()

        err = exc_info.value
        assert err.component_name == "sandbox"
        assert err.policy == MissingSemanticsPolicy.FAIL_CLOSED
        assert "FAIL_CLOSED" in str(err)
        assert "Start docker daemon" in str(err)

    def test_sync_fail_closed_passes_when_available(self) -> None:
        @enforce_missing_semantics(
            MissingSemanticsPolicy.FAIL_CLOSED,
            "sandbox",
            guard_fn=lambda: True,
        )
        def run_isolated_task() -> str:
            return "executed"

        assert run_isolated_task() == "executed"

    def test_sync_fail_fast_raises_error(self) -> None:
        @enforce_missing_semantics(
            MissingSemanticsPolicy.FAIL_FAST,
            "primary_database",
            guard_fn=lambda: False,
            repair_hint="Check DB connection string",
        )
        def boot_database() -> str:
            return "booted"

        with pytest.raises(MissingDependencyFailFastError) as exc_info:
            boot_database()

        assert exc_info.value.component_name == "primary_database"
        assert exc_info.value.policy == MissingSemanticsPolicy.FAIL_FAST

    def test_sync_fallback_calls_fallback_fn(self) -> None:
        @enforce_missing_semantics(
            MissingSemanticsPolicy.FALLBACK,
            "vision_multimodal",
            guard_fn=lambda: False,
            fallback_fn=lambda: "fallback_result",
        )
        def read_image() -> str:
            return "native_vision"

        assert read_image() == "fallback_result"

    def test_sync_fallback_returns_none_when_no_fallback_fn(self) -> None:
        @enforce_missing_semantics(
            MissingSemanticsPolicy.FALLBACK,
            "vision_multimodal",
            guard_fn=lambda: False,
        )
        def read_image() -> str | None:
            return "native_vision"

        assert read_image() is None

    @pytest.mark.asyncio
    async def test_async_fail_closed_raises_error(self) -> None:
        @enforce_missing_semantics(
            MissingSemanticsPolicy.FAIL_CLOSED,
            "credential_vault",
            guard_fn=lambda: False,
            action="get_secret",
            repair_hint="Initialize vault master key",
        )
        async def fetch_secret() -> str:
            return "secret_123"

        with pytest.raises(MissingDependencyFailClosedError) as exc_info:
            await fetch_secret()

        assert exc_info.value.component_name == "credential_vault"
        assert exc_info.value.action == "get_secret"

    @pytest.mark.asyncio
    async def test_async_fallback_calls_async_fallback_fn(self) -> None:
        async def async_fallback() -> str:
            return "async_fallback_ok"

        @enforce_missing_semantics(
            MissingSemanticsPolicy.FALLBACK,
            "specialty_router",
            guard_fn=lambda: False,
            fallback_fn=async_fallback,
        )
        async def route_model() -> str:
            return "opus_specialty"

        res = await route_model()
        assert res == "async_fallback_ok"


class TestSafeExecFailClosedGate:
    """Test safe_exec fail-closed gate when sandbox is required but unavailable."""

    @pytest.mark.asyncio
    async def test_safe_exec_raises_fail_closed_when_sandbox_unavailable(self) -> None:
        with pytest.raises(MissingDependencyFailClosedError) as exc_info:
            await safe_exec(
                "echo test",
                require_sandbox=True,
                sandbox_available=False,
            )

        err = exc_info.value
        assert err.component_name in ("sandbox", "sandbox_isolation")
        assert err.policy == MissingSemanticsPolicy.FAIL_CLOSED
        assert "sandbox" in str(err).lower()
