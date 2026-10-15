"""Vector database health probe for the doctor.

[INPUT]
- toolkits.vector.config::VectorStoreConfig (POS: Generic vector store configuration. Defines deployment modes and connection parameters, backend-agnostic.)
- toolkits.vector.qdrant::create_vector_store, embedded_fallback_paths (POS: Qdrant factory and the registry of stores running on the in-memory fallback)
- diagnostics.protocols::HealthReport (POS: Standard health check report)

[OUTPUT]
- check_qdrant_health: Check Qdrant vector database reachability; FAIL while an embedded store runs on the in-memory fallback.

[POS]
Harness-level doctor probe registered through probes.py; kept apart so the probe module stays within its line budget.
"""

from myrm_agent_harness.observability.diagnostics.protocols import HealthReport


async def check_qdrant_health() -> HealthReport:
    """Check Qdrant vector database reachability and that memory is being persisted."""
    try:
        try:
            from myrm_agent_harness.toolkits.vector import VectorStoreConfig
            from myrm_agent_harness.toolkits.vector.qdrant import create_vector_store, embedded_fallback_paths
        except ImportError:
            return HealthReport(
                component_name="VectorDB",
                status="warn",
                message="Advanced search features are not available.",
                detail="Vector toolkit not available, cannot perform Qdrant probe.",
                fix_suggestion="Install vector dependencies to enable advanced search.",
            )

        # The throwaway probe below never opens the real data directory, so a store that already degraded
        # to the in-memory fallback has to be reported from the live singleton registry.
        fallback_paths = embedded_fallback_paths()
        if fallback_paths:
            return HealthReport(
                component_name="VectorDB",
                status="fail",
                code="ERR_VECTOR_STORE_ON_MEMORY_FALLBACK",
                message="New memories are not being saved permanently.",
                detail=(
                    "The memory data folder could not be opened, so memory search fell back to temporary storage "
                    "that is cleared when the app restarts."
                ),
                fix_suggestion=(
                    "Quit any other running copy of the app, make sure the data folder is writable and has free "
                    "disk space, then restart the app."
                ),
                measured=f"{len(fallback_paths)} vector store(s) on the in-memory fallback",
                expected="persistent vector store",
                cause="The embedded Qdrant data directory could not be opened (locked, unwritable or full).",
            )

        # Use :memory: to test if Qdrant can initialize without locking a real directory
        config = VectorStoreConfig(local_path=":memory:")
        await create_vector_store(config=config)

        return HealthReport(
            component_name="VectorDB",
            status="pass",
            message="Vector database is healthy.",
            detail="Qdrant vector store is reachable and healthy.",
        )
    except ConnectionError as e:
        return HealthReport(
            component_name="VectorDB",
            status="fail",
            message="Vector database connection failed.",
            detail=f"Qdrant connection failed: {e}",
            fix_suggestion="Check vector database service status.",
        )
    except Exception as e:
        return HealthReport(
            component_name="VectorDB",
            status="fail",
            message="Vector database check failed.",
            detail=f"Qdrant health check failed: {e}",
            fix_suggestion="Check vector database service logs.",
        )
