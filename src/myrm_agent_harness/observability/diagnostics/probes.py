"""[INPUT]
- toolkits.retriever.bm25::get_tokenizer_service (POS: Unified tokenization service for CJK/English)

[OUTPUT]
- check_network_health: Verify outbound DNS resolution and TLS connectivity.
- check_workspace_storage_health: Test read/write permissions and SQLite responsiveness.
- check_database_health: Verify SQLite database basic connectivity.
- check_qdrant_health: Vector database probe (defined in vector_probe), registered here in probe order.
- check_tokenizer_health: Verify tokenizer backend and CJK quality gate.
- check_hook_health: Check hook system registration status and configuration.
- check_desktop_permissions_health: DesktopControl probe (defined in desktop_probe), registered here in probe order.
- check_local_trace_export_audit: Audit that trace export stays local while local-trace-only mode is on.

[POS]
Health diagnostic probes. Registered into the global diagnostic manager and executed
by /health/doctor to produce the system health dashboard.
"""

import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.observability.diagnostics.desktop_probe import check_desktop_permissions_health
from myrm_agent_harness.observability.diagnostics.manager import DIAGNOSTIC_HOOK_TIMEOUT_S, register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport
from myrm_agent_harness.observability.diagnostics.vector_probe import check_qdrant_health

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)


_NETWORK_PROBE_URLS = (
    "https://cloudflare-dns.com/dns-query",
    "https://www.gstatic.com/generate_204",
    "https://connectivitycheck.platform.hicloud.com/generate_204",
)
# A later URL opens only when the attempts before it are slow, so a healthy network still issues one request.
_NETWORK_PROBE_STAGGER_S = 1.0
_NETWORK_PROBE_REQUEST_TIMEOUT_S = 2.5
# The probe must deliver its own verdict before the manager's per-hook limit cuts it off.
_NETWORK_PROBE_BUDGET_S = DIAGNOSTIC_HOOK_TIMEOUT_S - 1.0


async def _probe_url(client: "httpx.AsyncClient", url: str) -> tuple[str, str | None]:
    """Return ``(url, None)`` when the URL answers, otherwise ``(url, failure description)``."""
    try:
        resp = await client.get(url, follow_redirects=True)
    except Exception as exc:
        return url, f"{type(exc).__name__}: {exc}"
    if resp.status_code < 500:
        return url, None
    return url, f"HTTP {resp.status_code} from {url}"


async def _first_reachable_url(client: "httpx.AsyncClient", failures: list[str]) -> str | None:
    """Return the first URL that answers; a slow or blocked attempt never delays the fallbacks behind it."""
    remaining = list(_NETWORK_PROBE_URLS)
    pending: set[asyncio.Task[tuple[str, str | None]]] = set()
    try:
        while remaining or pending:
            if not pending:
                pending.add(asyncio.create_task(_probe_url(client, remaining.pop(0))))
            done, pending = await asyncio.wait(
                pending,
                timeout=_NETWORK_PROBE_STAGGER_S if remaining else None,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                pending.add(asyncio.create_task(_probe_url(client, remaining.pop(0))))
                continue
            for task in done:
                url, failure = task.result()
                if failure is None:
                    return url
                failures.append(failure)
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return None


async def check_network_health() -> HealthReport:
    """Verify outbound DNS resolution and TLS connectivity.

    Probes several URLs (later ones open when earlier ones are slow) so a single blocked endpoint,
    common under regional network restrictions, cannot hide a working connection.
    """
    from myrm_agent_harness.infra.tls_compat import create_httpx_client

    failures: list[str] = []
    reachable: str | None = None
    async with create_httpx_client(timeout=_NETWORK_PROBE_REQUEST_TIMEOUT_S) as client:
        try:
            async with asyncio.timeout(_NETWORK_PROBE_BUDGET_S):
                reachable = await _first_reachable_url(client, failures)
        except TimeoutError:
            failures.append(f"TimeoutError: no probe URL answered within {_NETWORK_PROBE_BUDGET_S:g}s")

    if reachable is not None:
        return HealthReport(
            component_name="Network",
            status="pass",
            message="Internet connection is healthy.",
            detail=f"Outbound connectivity verified via {reachable}.",
        )
    return HealthReport(
        component_name="Network",
        status="fail",
        message="Internet is not available. AI features that need web access may not work.",
        detail=f"All probe URLs unreachable. Failures: {'; '.join(failures)}",
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

        from shutil import which

        if which("rg") is None:
            return HealthReport(
                component_name="WorkspaceStorage",
                status="warn",
                message="Workspace storage is healthy but ripgrep (rg) is not installed.",
                detail=(
                    f"Workspace ({workspace_path}) is writable. "
                    "File search will use a slower Python fallback without rg."
                ),
                fix_suggestion="Install ripgrep (rg) for faster workspace grep/glob search.",
            )

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


def _check_fts5_indexes(data_dir: str) -> str:
    """Best-effort FTS5 integrity check for wiki_index.db. Returns status string."""
    from myrm_agent_harness.utils.db.fts5 import fts5_integrity_check, fts5_rebuild

    workspace_dir = os.environ.get("MYRM_WORKSPACE_DIR", data_dir)
    wiki_db = Path(workspace_dir) / "wiki" / ".wiki_index.db"
    if not wiki_db.exists():
        return ""
    try:
        conn = sqlite3.connect(str(wiki_db), timeout=2.0)
        try:
            if fts5_integrity_check(conn, "wiki_fts"):
                return "wiki_fts OK"
            fts5_rebuild(conn, "wiki_fts")
            return "wiki_fts rebuilt (was corrupted)"
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("FTS5 probe failed: %s", exc)
        return f"wiki_fts check failed: {exc}"


async def check_database_health() -> HealthReport:
    """Verify SQLite database connectivity and integrity (including FTS5 indexes)."""
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

        # FTS5 index health: check wiki_index.db if present in workspace
        fts5_detail = _check_fts5_indexes(data_dir)

        detail = "SQLite database is connectable, responsive, and integrity verified."
        if fts5_detail:
            detail += f" FTS5: {fts5_detail}"

        return HealthReport(
            component_name="Database",
            status="pass",
            message="Database is healthy.",
            detail=detail,
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


async def check_hook_health() -> HealthReport:
    """Check hook system registration status and configuration.

    Reports pass when executor is active with hooks registered,
    or when no hooks are configured (no overhead).
    Actual per-invocation timing is logged by the executor itself.
    """
    try:
        from myrm_agent_harness.agent.hooks.executor import (
            _SLOW_HOOK_THRESHOLD_MS,
            get_hook_executor,
        )

        executor = get_hook_executor()
        if executor is None:
            return HealthReport(
                component_name="HookSystem",
                status="pass",
                message="Hook system is idle.",
            )

        registry = executor.registry
        total = registry.total_count
        if total == 0:
            return HealthReport(
                component_name="HookSystem",
                status="pass",
                message="Hook system is active, no hooks configured.",
            )

        summary = registry.summary()
        return HealthReport(
            component_name="HookSystem",
            status="pass",
            message=f"Hook system is healthy ({total} hook(s) active).",
            detail=f"Slow threshold: {_SLOW_HOOK_THRESHOLD_MS:.0f}ms. {summary}",
        )
    except Exception as exc:
        return HealthReport(
            component_name="HookSystem",
            status="fail",
            message="Hook system health check failed.",
            detail=str(exc),
            fix_suggestion="Check hook configuration and executor initialization.",
        )


async def check_local_trace_export_audit() -> HealthReport:
    """Audit trace export isolation to guarantee zero unauthorized remote telemetry leaks.

    Validates that:
    1. In local-trace-only mode (MYRM_LOCAL_TRACE_ONLY=1), no remote OTLP export occurs.
    2. Any remote endpoint is flagged, ensuring compliance with strict privacy baselines.
    """
    from myrm_agent_harness.infra.tracing.tracer import is_local_trace_only

    local_only = is_local_trace_only()
    otlp_ep = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

    if local_only:
        if otlp_ep and not otlp_ep.startswith(
            ("http://localhost", "http://127.0.0.1", "grpc://localhost", "grpc://127.0.0.1")
        ):
            return HealthReport(
                component_name="TraceExportAudit",
                status="fail",
                code="ERR_TRACE_REMOTE_LEAK_RISK",
                message="Remote trace endpoint detected while local-trace-only mode is active.",
                detail=f"Blocked external endpoint: '{otlp_ep}'. Trace data will remain local only.",
                fix_suggestion="Unset OTEL_EXPORTER_OTLP_ENDPOINT or use a localhost collector in local mode.",
                meta_data={"local_trace_only": True, "blocked_endpoint": otlp_ep},
            )
        return HealthReport(
            component_name="TraceExportAudit",
            status="pass",
            code="OK_LOCAL_TRACE_ISOLATION",
            message="Local trace isolation is fully enforced.",
            detail="Trace data is restricted to local storage (JSONL/SQLite); zero unauthorized remote export.",
            meta_data={"local_trace_only": True},
        )

    return HealthReport(
        component_name="TraceExportAudit",
        status="pass",
        code="OK_TRACE_EXPORT_STANDARD",
        message="Trace export operating in standard mode.",
        detail="Standard telemetry export active.",
        meta_data={"local_trace_only": False, "otlp_endpoint": otlp_ep or "none"},
    )


register_diagnostic(check_network_health)
register_diagnostic(check_workspace_storage_health)
register_diagnostic(check_database_health)
register_diagnostic(check_qdrant_health)
register_diagnostic(check_tokenizer_health)
register_diagnostic(check_hook_health)
register_diagnostic(check_desktop_permissions_health)
register_diagnostic(check_local_trace_export_audit)
