"""Auto-recovery orchestrator for browser tasks.

Automatically recovers incomplete browser tasks on application startup.
Supports parallel recovery with browser session pre-warming.


[INPUT]
- langgraph.checkpoint.base::BaseCheckpointSaver (POS: LangGraph checkpointer)
- pool.browser_pool::GlobalBrowserPool (POS: global browser pool)
- session_vault::SessionVault (POS: AES-256-GCM encrypted session storage)
- metadata::CheckpointMetadata, extract_metadata_from_messages (POS: metadata structure)
- metrics::CheckpointMetrics (POS: monitoring metrics)

[OUTPUT]
- AutoRecoveryOrchestrator: Startup recovery orchestrator
- ParallelRecoveryOrchestrator: Parallel recovery with pre-warming
- RecoveryContext: Recovery execution context

[POS]
Startup auto-recovery module. Scans incomplete checkpoints, rebuilds browser sessions, supports parallel recovery and pre-warming.
Integrated into the application startup flow for seamless task recovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from .metrics import CheckpointMetrics


class RecoverySummary(TypedDict, total=False):
    """Recovery operation summary."""

    success_count: int
    failure_count: int
    total_count: int
    failed_threads: list[str]
    elapsed_ms: float


if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from ..pool import GlobalBrowserPool
    from ..session import BrowserSession
    from ..session_vault import SessionVault
    from .metadata import CheckpointMetadata, SerializedMessage
    from .thread_registry import ThreadStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryContext:
    """Recovery execution context for a single task.

    Contains all information needed to reconstruct browser session state.

    Attributes:
        thread_id: LangGraph thread ID
        checkpoint_id: Checkpoint ID
        metadata: Extended checkpoint metadata
        messages: LangGraph message history
        last_updated_at: Checkpoint timestamp
    """

    thread_id: str
    checkpoint_id: str
    metadata: CheckpointMetadata
    messages: list[SerializedMessage]
    last_updated_at: float


class AutoRecoveryOrchestrator:
    """Automatic recovery orchestrator for browser tasks.

    Scans for incomplete checkpoints on startup and provides recovery context.
    Simple, single-threaded recovery suitable for most use cases.

    Usage:
        orchestrator = AutoRecoveryOrchestrator(checkpointer, vault)
        await orchestrator.initialize()

        contexts = await orchestrator.find_incomplete_tasks()
        for ctx in contexts:
            await recover_task(ctx)
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        thread_store: ThreadStore,
        session_vault: SessionVault | None = None,
        metrics: CheckpointMetrics | None = None,
        *,
        max_retries: int = 2,
        retry_delay_ms: float = 1000.0,
    ) -> None:
        """Initialize recovery orchestrator.

        Args:
            checkpointer: LangGraph checkpointer
            thread_store: Thread registry store
            session_vault: Optional Session Vault
            metrics: Optional shared metrics instance
            max_retries: Maximum recovery retry attempts (default 2)
            retry_delay_ms: Delay between retries in milliseconds (default 1000.0)
        """
        self._checkpointer = checkpointer
        self._thread_store = thread_store
        self._vault = session_vault
        self._metrics = metrics or CheckpointMetrics()
        self._max_retries = max_retries
        self._retry_delay_ms = retry_delay_ms
        self._skip_warmup_snapshot = False
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize orchestrator (call once at startup)."""
        if self._initialized:
            logger.warning("AutoRecoveryOrchestrator already initialized")
            return

        self._initialized = True
        logger.info("AutoRecoveryOrchestrator: initialized")

    async def find_incomplete_tasks(
        self,
        max_age_hours: float = 24.0,
    ) -> list[RecoveryContext]:
        """Find incomplete browser tasks from checkpoints.

        Args:
            max_age_hours: Maximum age of checkpoints to consider (default 24h)

        Returns:
            List of recovery contexts for incomplete tasks
        """
        if not self._initialized:
            raise RuntimeError("Orchestrator not initialized. Call initialize() first.")

        start_time = time.perf_counter()

        try:
            # Scan active threads from registry
            thread_records = await self._thread_store.find_active_threads(max_age_hours=max_age_hours)

            if not thread_records:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    "AutoRecoveryOrchestrator: no active threads (elapsed=%.1fms)",
                    elapsed_ms,
                )
                return []

            # Build recovery contexts from thread records
            contexts: list[RecoveryContext] = []

            for record in thread_records:
                try:
                    # Get latest checkpoint tuple (includes metadata)
                    config = {"configurable": {"thread_id": record.thread_id, "checkpoint_ns": ""}}
                    checkpoint_tuple = await self._checkpointer.aget_tuple(config)

                    if not checkpoint_tuple:
                        logger.warning(
                            "AutoRecoveryOrchestrator: no checkpoint found (thread_id=%s)",
                            record.thread_id,
                        )
                        continue

                    # Extract checkpoint and metadata from tuple
                    checkpoint = checkpoint_tuple.checkpoint
                    lg_metadata = checkpoint_tuple.metadata or {}

                    # Browser metadata is in lg_metadata["browser"]
                    browser_metadata = lg_metadata.get("browser", {})

                    # If no browser metadata in checkpoint, try extracting from messages
                    if not browser_metadata:
                        messages = checkpoint.get("channel_values", {}).get("messages", [])
                        if messages:
                            from .metadata import extract_metadata_from_messages

                            try:
                                browser_metadata = extract_metadata_from_messages(messages)
                            except Exception:
                                browser_metadata = {}

                    # Get messages for recovery context
                    messages = checkpoint.get("channel_values", {}).get("messages", [])

                    # Build recovery context
                    context = RecoveryContext(
                        thread_id=record.thread_id,
                        checkpoint_id=checkpoint["id"],
                        metadata=browser_metadata,
                        messages=messages,
                        last_updated_at=checkpoint.get("ts", 0) / 1000,  # ns to seconds
                    )

                    contexts.append(context)

                except Exception as exc:
                    logger.error(
                        "AutoRecoveryOrchestrator: failed to load checkpoint (thread_id=%s): %s",
                        record.thread_id,
                        exc,
                    )
                    continue

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "AutoRecoveryOrchestrator: scanned checkpoints (found=%d, elapsed=%.1fms)",
                len(contexts),
                elapsed_ms,
            )

            return contexts
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Failed to scan checkpoints: %s (elapsed=%.1fms)",
                exc,
                elapsed_ms,
                exc_info=True,
            )
            self._metrics.recovery_failures += 1
            return []

    async def recover_session(
        self,
        ctx: RecoveryContext,
        browser_session: BrowserSession,
    ) -> bool:
        """Recover browser session state from checkpoint context with retry.

        Args:
            ctx: Recovery context
            browser_session: Target browser session

        Returns:
            True if recovery succeeded
        """
        for attempt in range(self._max_retries + 1):
            start_time = time.perf_counter()

            try:
                from .session_state import apply_storage_state

                # 1. Apply cookies + localStorage (before navigation)
                if self._vault and ctx.metadata.get("session_domain"):
                    domain = ctx.metadata["session_domain"]

                    entry = await self._vault.load(domain)
                    if entry:
                        # Apply cookies + localStorage to browser context
                        await apply_storage_state(browser_session, entry.storage_state)
                        logger.info(
                            "Recovery: session restored for %s (thread_id=%s)",
                            domain,
                            ctx.thread_id,
                        )
                        self._metrics.vault_cache_hits += 1
                    else:
                        logger.warning(
                            "Recovery: no session found for %s (may have expired)",
                            domain,
                        )

                # 2. Navigate to last URL (localStorage via init script will auto-apply)
                if ctx.metadata.get("current_url"):
                    url = ctx.metadata["current_url"]

                    # Create tab and navigate
                    await browser_session.new_tab(url)

                    logger.info(
                        "Recovery: navigated to %s (thread_id=%s)",
                        url,
                        ctx.thread_id,
                    )

                # 3. Take snapshot to refresh state (optional for warmup optimization)
                if not self._skip_warmup_snapshot:
                    await browser_session.snapshot()
                    logger.debug("Recovery: snapshot taken (thread_id=%s)", ctx.thread_id)
                else:
                    logger.debug("Recovery: snapshot skipped (skip_warmup_snapshot=True)")

                # 4. Update metrics
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.recovery_count += 1
                self._metrics.recovery_total_ms += elapsed_ms

                logger.info(
                    "Recovery: succeeded (thread_id=%s, elapsed=%.1fms, attempt=%d)",
                    ctx.thread_id,
                    elapsed_ms,
                    attempt + 1,
                )

                return True
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                if attempt < self._max_retries:
                    # Retry with backoff
                    logger.warning(
                        "Recovery: attempt %d failed (thread_id=%s, elapsed=%.1fms), retrying in %.0fms: %s",
                        attempt + 1,
                        ctx.thread_id,
                        elapsed_ms,
                        self._retry_delay_ms,
                        exc,
                    )
                    await asyncio.sleep(self._retry_delay_ms / 1000)
                    continue
                else:
                    # Final failure
                    self._metrics.recovery_failures += 1
                    self._metrics.recovery_total_ms += elapsed_ms

                    logger.error(
                        "Recovery: failed after %d attempts (thread_id=%s, total_elapsed=%.1fms): %s",
                        self._max_retries + 1,
                        ctx.thread_id,
                        elapsed_ms,
                        exc,
                        exc_info=True,
                    )

                    return False

        return False


class ParallelRecoveryOrchestrator:
    """Parallel recovery orchestrator with browser session pre-warming.

    Advanced recovery strategy that:
    1. Discovers incomplete tasks in parallel
    2. Pre-warms browser sessions concurrently
    3. Recovers multiple tasks in parallel

    Significantly faster than sequential recovery for multi-task scenarios.

    Usage:
        orchestrator = ParallelRecoveryOrchestrator(
            checkpointer, browser_pool, vault
        )
        await orchestrator.initialize()

        results = await orchestrator.recover_all()
        print(f"Recovered {results['success_count']} tasks")
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        thread_store: ThreadStore,
        browser_pool: GlobalBrowserPool,
        session_vault: SessionVault | None = None,
        metrics: CheckpointMetrics | None = None,
        *,
        max_concurrent_recoveries: int = 3,
        max_retries: int = 2,
        retry_delay_ms: float = 1000.0,
        skip_warmup_snapshot: bool = False,
    ) -> None:
        """Initialize parallel recovery orchestrator.

        Args:
            checkpointer: LangGraph checkpointer
            thread_store: Thread registry store
            browser_pool: Global browser pool for session creation
            session_vault: Optional Session Vault
            metrics: Optional shared metrics instance
            skip_warmup_snapshot: Skip taking snapshot during warmup recovery
            max_concurrent_recoveries: Max parallel recoveries (default 3)
            max_retries: Maximum recovery retry attempts (default 2)
            retry_delay_ms: Delay between retries in milliseconds (default 1000.0)
        """
        self._base_orchestrator = AutoRecoveryOrchestrator(
            checkpointer,
            thread_store,
            session_vault,
            metrics,
            max_retries=max_retries,
            retry_delay_ms=retry_delay_ms,
        )
        self._browser_pool = browser_pool
        self._max_concurrent = max_concurrent_recoveries
        self._skip_warmup_snapshot = skip_warmup_snapshot

    @property
    def metrics(self) -> CheckpointMetrics:
        """Get checkpoint metrics."""
        return self._base_orchestrator._metrics

    async def initialize(self) -> None:
        """Initialize orchestrator (call once at startup)."""
        await self._base_orchestrator.initialize()
        logger.info(
            "ParallelRecoveryOrchestrator: initialized (max_concurrent=%d)",
            self._max_concurrent,
        )

    async def recover_all(
        self,
        max_age_hours: float = 24.0,
    ) -> RecoverySummary:
        """Discover and recover all incomplete tasks in parallel.

        Args:
            max_age_hours: Maximum age of checkpoints to consider

        Returns:
            Recovery summary with success/failure counts and details
        """
        start_time = time.perf_counter()

        # 1. Find incomplete tasks
        contexts = await self._base_orchestrator.find_incomplete_tasks(max_age_hours)

        if not contexts:
            logger.info("ParallelRecoveryOrchestrator: no incomplete tasks found")
            return {
                "success_count": 0,
                "failure_count": 0,
                "total_count": 0,
                "elapsed_ms": (time.perf_counter() - start_time) * 1000,
            }

        logger.info(
            "ParallelRecoveryOrchestrator: found %d incomplete task(s), starting parallel recovery",
            len(contexts),
        )

        # 2. Parallel recovery with semaphore
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def recover_one(ctx: RecoveryContext) -> tuple[str, bool]:
            """Recover single task with semaphore."""
            async with semaphore:
                # Create browser session (pre-warmed from pool)
                from ..session import BrowserSession

                session = BrowserSession(
                    browser_pool=self._browser_pool,
                    context_type="AGENT",
                    context_key=ctx.thread_id,
                    session_vault=self._base_orchestrator._vault,
                )

                try:
                    success = await self._base_orchestrator.recover_session(ctx, session)
                    return (ctx.thread_id, success)
                finally:
                    await session.close()

        # 3. Execute recoveries in parallel
        results = await asyncio.gather(
            *[recover_one(ctx) for ctx in contexts],
            return_exceptions=True,
        )

        # 4. Analyze results
        success_count = 0
        failure_count = 0
        failed_threads: list[str] = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failure_count += 1
                failed_threads.append(contexts[i].thread_id)
                logger.error(
                    "Recovery exception for thread_id=%s: %s",
                    contexts[i].thread_id,
                    result,
                )
            else:
                thread_id, success = result
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    failed_threads.append(thread_id)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "ParallelRecoveryOrchestrator: completed (success=%d, failure=%d, elapsed=%.1fms)",
            success_count,
            failure_count,
            elapsed_ms,
        )

        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "total_count": len(contexts),
            "failed_threads": failed_threads,
            "elapsed_ms": elapsed_ms,
        }
