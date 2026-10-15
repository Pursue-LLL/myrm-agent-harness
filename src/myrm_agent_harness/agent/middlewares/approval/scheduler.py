"""Approval timeout scheduler — auto-resumes agents when approval requests expire.

Prevents agents from permanently suspending when no user responds to an
approval or structured clarification request. Covers three scenarios:
- Web UI: browser closed/refreshed before timeout (approval or clarify form)
- Channels: user never responds to /approve prompt
- Cron: fully unattended execution

The scheduler is a process-level singleton. Each pending approval is tracked
by a unique key (chat_id or channel:peer). When the timeout fires, the
provided callback executes the full resume flow (construct resume_value,
run agent stream, persist results).

[INPUT]

[OUTPUT]
- Auto-resume callback execution on timeout
- Idempotent resolution via `resolve_if_first` (prevents race between timeout and manual resume)
- `reopen` re-arms resolution for a key whose resumed run stopped at a new interrupt without a timer

[POS]
Stateless in-memory scheduler. Timeouts are lost on process restart,
which is acceptable — the frontend/channel will show "expired" state,
and the user can manually resume or start a new conversation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

ResumeCallback = Callable[[dict[str, object]], Awaitable[None]]


class ApprovalTimeoutScheduler:
    """Schedules auto-resume when approval requests timeout.

    Resolution is idempotent per key: whichever side (timeout or manual resume)
    claims it first wins; the loser is a no-op. This eliminates the race
    condition where both could fire concurrently. The manual path claims through
    ``resolve_if_first`` (which also cancels the timer); the timer claims directly.

    Usage::

        scheduler = ApprovalTimeoutScheduler.get()

        # Register timeout (in SSE stream or channel event handler)
        scheduler.schedule(
            key="chat-123",
            timeout_seconds=300,
            behavior="deny",
            resume_callback=my_callback)

        # Resolve when manual resume arrives (returns False if timeout already won)
        scheduler.resolve_if_first("chat-123")
    """

    _instance: ApprovalTimeoutScheduler | None = None

    @classmethod
    def get(cls) -> ApprovalTimeoutScheduler:
        """Return the process-level singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._resolved_keys: set[str] = set()

    def schedule(
        self,
        key: str,
        timeout_seconds: float,
        behavior: str,
        resume_callback: ResumeCallback,
        *,
        resume_value_override: dict[str, object] | None = None,
    ) -> None:
        """Register a timeout guard for a pending approval.

        Args:
            key: Unique identifier (chat_id for Web UI, channel:peer for channels).
            timeout_seconds: Seconds until auto-resume fires.
            behavior: "deny" or "allow" — determines the auto-resume decision.
            resume_callback: Async function receiving the constructed resume_value.
                             Responsible for executing the full Agent resume flow.
            resume_value_override: When set, used as resume_value instead of approval decision payload.
        """
        self.cancel(key)
        self._resolved_keys.discard(key)
        task = asyncio.create_task(
            self._run(key, timeout_seconds, behavior, resume_callback, resume_value_override),
            name=f"approval-timeout:{key}",
        )
        self._tasks[key] = task
        logger.info(
            "Approval timeout scheduled: key=%s, timeout=%ss, behavior=%s, override=%s",
            key,
            timeout_seconds,
            behavior,
            resume_value_override is not None,
        )

    def resolve_if_first(self, key: str) -> bool:
        """Atomically resolve a pending approval key on the manual path. Returns True only for the first caller.

        The manual resume path must call this before proceeding; a True result
        also cancels the pending timer. The loser (second caller) gets False and
        must abort. The timer path claims the key itself and never cancels itself.
        """
        if not self._claim(key):
            return False
        self.cancel(key)
        return True

    def reopen(self, key: str) -> None:
        """Accept a fresh resolution for ``key`` after the run stopped at a new interrupt that carries no timer.

        A pending timer is left untouched.
        """
        self._resolved_keys.discard(key)

    def _claim(self, key: str) -> bool:
        """Mark ``key`` resolved. Returns False when it already was."""
        if key in self._resolved_keys:
            logger.debug("Approval already resolved (duplicate): key=%s", key)
            return False
        self._resolved_keys.add(key)
        return True

    async def _run(
        self,
        key: str,
        timeout: float,
        behavior: str,
        callback: ResumeCallback,
        resume_value_override: dict[str, object] | None,
    ) -> None:
        task = asyncio.current_task()
        try:
            await asyncio.sleep(timeout)
            if not self._claim(key):
                logger.info("Approval timeout lost race (already resolved): key=%s", key)
                return
            # Detach before resuming: the resumed run may stop at a new interrupt and arm the next
            # timer for this key, and `schedule` cancels whatever task is registered under the key.
            self._detach(key, task)
            resume_value: dict[str, object]
            if resume_value_override is not None:
                resume_value = resume_value_override
                logger.warning(
                    "HITL timeout fired with custom resume_value: key=%s after %ss",
                    key,
                    timeout,
                )
            else:
                approved = behavior == "allow"
                decision = "approve" if approved else "reject"
                resume_value = {
                    "decision": decision,
                    "feedback": f"Auto-{'approved' if approved else 'rejected'}: approval timeout ({timeout:.0f}s)",
                }
                logger.warning("Approval timeout fired: key=%s, auto-%s after %ss", key, decision, timeout)
                _record_timeout_audit(key, decision, timeout)
            await callback(resume_value)
        except asyncio.CancelledError:
            logger.debug("Approval timeout cancelled (manual resume): key=%s", key)
        except Exception:
            logger.exception("Approval timeout callback failed: key=%s", key)
        finally:
            self._detach(key, task)

    def _detach(self, key: str, task: asyncio.Task[None] | None) -> None:
        """Drop the registry entry only if it still belongs to ``task`` (a newer timer may own the key)."""
        if task is not None and self._tasks.get(key) is task:
            del self._tasks[key]

    def cancel(self, key: str) -> bool:
        """Cancel a pending timeout. Returns True if a timer was actually cancelled."""
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
            logger.debug("Approval timeout cancelled: key=%s", key)
            return True
        return False

    def cancel_all(self) -> int:
        """Cancel all pending timeouts. Returns count of cancelled timers."""
        count = 0
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
                count += 1
        self._tasks.clear()
        self._resolved_keys.clear()
        return count

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())


def _record_timeout_audit(key: str, decision: str, timeout: float) -> None:
    """Record the timeout auto-decision to the security audit trail."""
    try:
        from myrm_agent_harness.agent.security.audit import record_decision

        approved = decision == "approve"
        record_decision(
            tool_name="approval_timeout",
            decision="TIMEOUT_APPROVED" if approved else "TIMEOUT_DENIED",
            reason=f"Auto-{'approved' if approved else 'rejected'} after {timeout:.0f}s timeout (key={key})",
        )
    except Exception:
        logger.debug("Could not record timeout audit for key=%s", key)
