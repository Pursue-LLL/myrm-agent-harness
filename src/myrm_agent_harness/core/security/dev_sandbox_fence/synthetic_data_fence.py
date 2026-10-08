"""Approved Synthetic Data Fence redirecting production data requests to masked replicas."""

from __future__ import annotations

import threading

from .types import FenceInspectionResult, SyntheticDataFixture, ViolationType


class SyntheticDataFence:
    """Redirects database connections in dev mode to approved synthetic or masked read-only fixtures."""

    def __init__(self, load_defaults: bool = True) -> None:
        self._lock = threading.Lock()
        self._fixtures: dict[str, SyntheticDataFixture] = {}
        if load_defaults:
            self._load_standard_fixtures()

    def _load_standard_fixtures(self) -> None:
        """Register default approved synthetic test fixtures."""
        default_fixtures = [
            SyntheticDataFixture(
                fixture_id="synthetic_sqlite_memory",
                database_type="sqlite",
                read_only_uri="sqlite:///:memory:",
                sample_count=200,
                description="In-memory synthetic SQLite fixture with sanitized test schema",
            ),
            SyntheticDataFixture(
                fixture_id="synthetic_mock_postgres",
                database_type="postgres",
                read_only_uri="mock://dev-synthetic-postgres-replica:5432/test_db",
                sample_count=500,
                description="Synthetic read-only Postgres replica for adapter testing",
            ),
            SyntheticDataFixture(
                fixture_id="synthetic_mock_mysql",
                database_type="mysql",
                read_only_uri="mock://dev-synthetic-mysql-replica:3306/test_db",
                sample_count=300,
                description="Synthetic read-only MySQL replica with approved masked records",
            ),
        ]
        for fixture in default_fixtures:
            self._fixtures[fixture.fixture_id] = fixture

    def register_fixture(self, fixture: SyntheticDataFixture) -> None:
        """Register a new synthetic or masked test dataset fixture."""
        with self._lock:
            self._fixtures[fixture.fixture_id] = fixture

    def unregister_fixture(self, fixture_id: str) -> bool:
        """Remove a synthetic fixture from registry."""
        with self._lock:
            return self._fixtures.pop(fixture_id, None) is not None

    def list_fixtures(self) -> list[SyntheticDataFixture]:
        """List all available approved synthetic data fixtures."""
        with self._lock:
            return list(self._fixtures.values())

    def get_fixture(self, fixture_id: str) -> SyntheticDataFixture | None:
        """Retrieve synthetic fixture by identifier."""
        with self._lock:
            return self._fixtures.get(fixture_id)

    def inspect_db_connection(
        self, requested_uri: str, enforce_synthetic: bool = True
    ) -> FenceInspectionResult:
        """Vet database connection URI in dev mode, substituting real DBs with synthetic fixtures."""
        lowered = requested_uri.lower().strip()

        # Check if already pointing to a mock or memory fixture
        if ":memory:" in lowered or lowered.startswith("mock://") or "synthetic" in lowered:
            return FenceInspectionResult(
                allowed=True,
                violation_type=None,
                reason="Connection already targets approved synthetic or mock fixture",
                substituted_target=requested_uri,
            )

        # Detect database type to find best synthetic match
        db_type = "sqlite"
        if "postgres" in lowered:
            db_type = "postgres"
        elif "mysql" in lowered:
            db_type = "mysql"

        with self._lock:
            # Find matching synthetic fixture
            matched_fixture = next(
                (f for f in self._fixtures.values() if f.database_type == db_type),
                None,
            )
            if not matched_fixture:
                matched_fixture = self._fixtures.get("synthetic_sqlite_memory")

        if not enforce_synthetic:
            return FenceInspectionResult(
                allowed=True,
                violation_type=None,
                reason="Synthetic data enforcement is disabled by policy",
                substituted_target=requested_uri,
            )

        if matched_fixture:
            return FenceInspectionResult(
                allowed=True,
                violation_type=ViolationType.PROD_CREDENTIAL_SUBSTITUTION,
                reason=f"Production database connection intercepted and substituted with approved synthetic fixture '{matched_fixture.fixture_id}'",
                substituted_target=matched_fixture.read_only_uri,
            )

        return FenceInspectionResult(
            allowed=False,
            violation_type=ViolationType.PROD_CREDENTIAL_SUBSTITUTION,
            reason="Real database access blocked in dev mode and no synthetic fixture is configured",
            substituted_target=None,
        )
