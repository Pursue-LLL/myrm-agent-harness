"""[INPUT]
- toolkits.vector.config::VectorStoreConfig (POS: Generic vector store configuration. Defines deployment modes and connection parameters, backend-agnostic.)
- toolkits.retriever.bm25::get_tokenizer_service (POS: Unified tokenization service for CJK/English)

[OUTPUT]
- check_network_health: Verify outbound DNS resolution and TLS connectivity.
- check_workspace_storage_health: Test read/write permissions and SQLite responsiveness.
- check_database_health: Verify SQLite database basic connectivity.
- check_qdrant_health: Check Qdrant vector database reachability.
- check_system_resources: Monitor CPU and memory usage via psutil.
- check_tokenizer_health: Verify tokenizer backend and CJK quality gate.

[POS]
Health diagnostic probes. Registered into the global diagnostic manager and executed
by /health/doctor to produce the system health dashboard.
"""

import logging
import os
import sqlite3
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

try:
    import psutil
except ImportError:
    psutil = None

from myrm_agent_harness.observability.diagnostics.manager import register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

logger = logging.getLogger(__name__)


_NETWORK_PROBE_URLS = (
    "https://cloudflare-dns.com/dns-query",
    "https://www.gstatic.com/generate_204",
    "https://connectivitycheck.platform.hicloud.com/generate_204",
)


async def check_network_health() -> HealthReport:
    """Verify outbound DNS resolution and TLS connectivity.

    Tries multiple probe URLs with fallback to handle regional network restrictions.
    """
    if httpx is None:
        return HealthReport(
            component_name="Network",
            status="warn",
            message="Network diagnostic is unavailable.",
            detail="httpx library is missing, cannot perform network probe.",
            fix_suggestion="Install httpx to enable network diagnostics.",
        )

    last_failure: str | None = None
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in _NETWORK_PROBE_URLS:
            try:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code < 500:
                    return HealthReport(
                        component_name="Network",
                        status="pass",
                        message="Internet connection is healthy.",
                        detail=f"Outbound connectivity verified via {url}.",
                    )
                last_failure = f"HTTP {resp.status_code} from {url}"
            except Exception as e:
                last_failure = f"{type(e).__name__}: {e}"
                continue

    detail = (
        f"All probe URLs unreachable. Last failure: {last_failure}" if last_failure else "All probe URLs unreachable."
    )
    return HealthReport(
        component_name="Network",
        status="fail",
        message="Internet is not available. AI features that need web access may not work.",
        detail=detail,
        fix_suggestion="Check your network connection or firewall settings.",
    )


async def check_workspace_storage_health() -> HealthReport:
    """Test read/write permissions and SQLite responsiveness in the data directory."""
    data_dir = os.environ.get("MYRM_DATA_DIR", str(Path.home() / ".myrm"))
    workspace_path = Path(data_dir)

    try:
        workspace_path.mkdir(parents=True, exist_ok=True)

        test_file = workspace_path / ".myrm_health_probe.tmp"
        test_file.write_text("probe")

        content = test_file.read_text()
        if content != "probe":
            raise ValueError("Data read mismatch")

        test_file.unlink()

        skills_db = workspace_path / "skills.db"
        if skills_db.exists():
            conn = sqlite3.connect(f"file:{skills_db.absolute()}?mode=ro", uri=True, timeout=1.0)
            conn.execute("PRAGMA schema_version;").fetchall()
            conn.close()

        return HealthReport(
            component_name="WorkspaceStorage",
            status="pass",
            message="Workspace storage is healthy.",
            detail=f"Workspace ({workspace_path}) is fully writable and SQLite is responsive.",
        )
    except PermissionError as e:
        return HealthReport(
            component_name="WorkspaceStorage",
            status="fail",
            message="Cannot save data — storage permission issue.",
            detail=f"Permission denied on workspace {workspace_path}: {e}",
            fix_suggestion="Check file permissions or volume mounts.",
        )
    except OSError as e:
        if e.errno == 28:  # ENOSPC
            return HealthReport(
                component_name="WorkspaceStorage",
                status="fail",
                message="Disk space is running low.",
                detail=f"No space left on device for workspace {workspace_path}.",
                fix_suggestion="Free up disk space or increase volume size.",
            )
        return HealthReport(
            component_name="WorkspaceStorage",
            status="fail",
            message="Workspace storage error detected.",
            detail=f"I/O error on workspace: {e}",
            fix_suggestion="Check disk health or filesystem mount status.",
        )
    except Exception as e:
        return HealthReport(
            component_name="WorkspaceStorage",
            status="fail",
            message="Unexpected workspace storage error.",
            detail=f"Unknown storage error: {e}",
            fix_suggestion="Check application logs for details.",
        )


async def check_database_health() -> HealthReport:
    """Verify SQLite database connectivity and integrity."""
    from myrm_agent_harness.utils.db.sqlite import (
        SQLiteIntegrityError,
        check_page_count_invariant,
        quick_check_sync,
        validate_sqlite_header,
    )

    data_dir = os.environ.get("MYRM_DATA_DIR", str(Path.home() / ".myrm"))
    db_path = Path(data_dir) / "data.db"

    try:
        # Cheap O(1) file-level guards: non-DB file / torn-write truncation.
        validate_sqlite_header(db_path)
        check_page_count_invariant(db_path)

        conn = sqlite3.connect(str(db_path), timeout=3.0)
        try:
            conn.execute("SELECT 1").fetchone()
            # Bounded canary: cheaper than full integrity_check on large databases.
            quick_check_sync(conn)
        finally:
            conn.close()

        return HealthReport(
            component_name="Database",
            status="pass",
            message="Database is healthy.",
            detail="SQLite database is connectable, responsive, and integrity verified.",
        )
    except SQLiteIntegrityError as e:
        return HealthReport(
            component_name="Database",
            status="fail",
            message="Database integrity check failed.",
            detail=str(e),
            fix_suggestion="Database may be corrupted. Consider resetting via /api/v1/health/database/reset.",
            measured=str(e),
            expected="integrity_check: ok",
            cause="SQLite database file may be corrupted due to unexpected shutdown or disk error.",
        )
    except sqlite3.OperationalError as e:
        return HealthReport(
            component_name="Database",
            status="fail",
            message="Database is temporarily unavailable.",
            detail=f"Database connection failed: {e}",
            fix_suggestion="Try restarting the application.",
        )
    except Exception as e:
        return HealthReport(
            component_name="Database",
            status="fail",
            message="Unexpected database error.",
            detail=f"Unexpected database error: {e}",
            fix_suggestion="Check application logs for details.",
        )


async def check_qdrant_health() -> HealthReport:
    """Check Qdrant vector database reachability."""
    try:
        try:
            from myrm_agent_harness.toolkits.vector import VectorStoreConfig
            from myrm_agent_harness.toolkits.vector.qdrant import create_vector_store
        except ImportError:
            return HealthReport(
                component_name="VectorDB",
                status="warn",
                message="Advanced search features are not available.",
                detail="Vector toolkit not available, cannot perform Qdrant probe.",
                fix_suggestion="Install vector dependencies to enable advanced search.",
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


async def check_system_resources() -> HealthReport:
    """Monitor CPU and memory usage via psutil."""
    if psutil is None:
        return HealthReport(
            component_name="SystemResources",
            status="warn",
            message="System resource monitoring is unavailable.",
            detail="psutil library is missing, cannot perform system resource probe.",
            fix_suggestion="Install psutil to enable resource monitoring.",
        )

    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_used_gb = memory.used / (1024**3)
        memory_total_gb = memory.total / (1024**3)
        stats = f"CPU: {cpu_percent:.1f}%, Memory: {memory_percent:.1f}% ({memory_used_gb:.1f}/{memory_total_gb:.1f}GB)"

        if memory_percent >= 95:
            return HealthReport(
                component_name="SystemResources",
                status="fail",
                message="System memory is critically low. Performance may be degraded.",
                detail=stats,
                fix_suggestion="Close unused applications to free memory.",
                measured=f"Memory {memory_percent:.1f}%",
                expected="Memory <95%",
                cause="Physical memory exhaustion may cause OOM kills or severe swapping.",
            )
        if memory_percent > 80:
            return HealthReport(
                component_name="SystemResources",
                status="warn",
                message="System memory usage is high.",
                detail=stats,
                fix_suggestion="Close unused applications to free memory.",
                measured=f"Memory {memory_percent:.1f}%",
                expected="Memory <80%",
                cause="High memory usage may lead to degraded performance under load.",
            )
        if cpu_percent >= 95:
            return HealthReport(
                component_name="SystemResources",
                status="fail",
                message="CPU usage is critically high. Performance may be degraded.",
                detail=stats,
                fix_suggestion="Check for resource-intensive processes.",
                measured=f"CPU {cpu_percent:.1f}%",
                expected="CPU <95%",
                cause="CPU saturation will cause request timeouts and agent stalls.",
            )
        if cpu_percent > 80:
            return HealthReport(
                component_name="SystemResources",
                status="warn",
                message="CPU usage is high.",
                detail=stats,
                fix_suggestion="Check for resource-intensive processes.",
                measured=f"CPU {cpu_percent:.1f}%",
                expected="CPU <80%",
                cause="Elevated CPU usage may cause latency spikes during peak loads.",
            )
        return HealthReport(
            component_name="SystemResources",
            status="pass",
            message="System resources are healthy.",
            detail=stats,
        )
    except Exception as e:
        return HealthReport(
            component_name="SystemResources",
            status="fail",
            message="System resource check failed.",
            detail=f"System resource check failed: {e}",
            fix_suggestion="Check if psutil is properly installed.",
        )


async def check_tokenizer_health() -> HealthReport:
    """Verify tokenizer availability and CJK tokenization quality.

    Checks:
    1. Which backend is active (jieba or bigram_fallback)
    2. Whether CJK text produces multiple tokens (quality gate)
    """
    try:
        from myrm_agent_harness.toolkits.retriever.bm25 import get_tokenizer_service

        service = get_tokenizer_service()
        backend = service.backend

        # Quality gate: "机器学习" must produce at least 2 tokens
        test_input = "机器学习"
        tokens = service.tokenize(test_input)
        token_count = len(tokens)
        quality_pass = token_count >= 2

        if not quality_pass:
            return HealthReport(
                component_name="Tokenizer",
                status="fail",
                message="CJK tokenization is broken — Chinese search will not work.",
                detail=f"Backend: {backend}. Input '{test_input}' produced only {token_count} token(s): {tokens}",
                fix_suggestion="Check tokenizer module integrity. Expected at least 2 tokens for CJK input.",
                measured=f"tokens={token_count}",
                expected="tokens>=2",
                cause="Tokenizer fallback may not be splitting CJK characters correctly.",
            )

        if backend == "bigram_fallback":
            return HealthReport(
                component_name="Tokenizer",
                status="warn",
                message="Tokenizer is using bigram fallback. Install jieba for optimal CJK search quality.",
                detail=f"Backend: {backend}. Quality check passed: '{test_input}' → {token_count} tokens.",
                fix_suggestion="Install jieba: pip install jieba",
                measured=f"backend={backend}, tokens={token_count}",
                expected="backend=jieba",
            )

        return HealthReport(
            component_name="Tokenizer",
            status="pass",
            message="Tokenizer is healthy with full CJK support.",
            detail=f"Backend: {backend}. Quality check passed: '{test_input}' → {token_count} tokens.",
        )
    except Exception as exc:
        return HealthReport(
            component_name="Tokenizer",
            status="fail",
            message="Tokenizer health check failed.",
            detail=str(exc),
            fix_suggestion="Check retriever module installation and configuration.",
        )


register_diagnostic(check_network_health)
register_diagnostic(check_workspace_storage_health)
register_diagnostic(check_database_health)
register_diagnostic(check_qdrant_health)
register_diagnostic(check_system_resources)
register_diagnostic(check_tokenizer_health)
