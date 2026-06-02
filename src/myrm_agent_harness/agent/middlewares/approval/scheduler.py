"""Approval timeout scheduler — auto-resumes agents when approval requests expire.

Prevents agents from permanently suspending when no user responds to an
approval request. Covers three scenarios:
- Web UI: browser closed/refreshed before timeout
- Channels: user never responds to /approve prompt
- Cron: fully unattended execution

The scheduler is a process-level singleton. Each pending approval is tracked
by a unique key (chat_id or channel:peer). When the timeout fires, the
provided callback executes the full resume flow (construct resume_value,
run agent stream, persist results).

[INPUT]

[OUTPUT]
- Auto-resume callback execution on timeout
- Cancellation when manual resume arrives first

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

    Usage::

        scheduler = ApprovalTimeoutScheduler.get()

        # Register timeout (in SSE stream or channel event handler)
        scheduler.schedule(
            key="chat-123",
            timeout_seconds=300,
            behavior="deny",
            resume_callback=my_callback)

        # Cancel when manual resume arrives
        scheduler.cancel("chat-123")
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

    def schedule(self, key: str, timeout_seconds: float, behavior: str, resume_callback: ResumeCallback) -> None:
        """Register a timeout guard for a pending approval.

        Args:
            key: Unique identifier (chat_id for Web UI, channel:peer for channels).
            timeout_seconds: Seconds until auto-resume fires.
            behavior: "deny" or "allow" — determines the auto-resume decision.
            resume_callback: Async function receiving the constructed resume_value.
                             Responsible for executing the full Agent resume flow.
        """
        self.cancel(key)
        task = asyncio.create_task(
            self._run(key, timeout_seconds, behavior, resume_callback), name=f"approval-timeout:{key}"
        )
        self._tasks[key] = task
        logger.info("Approval timeout scheduled: key=%s, timeout=%ss, behavior=%s", key, timeout_seconds, behavior)

    async def _run(self, key: str, timeout: float, behavior: str, callback: ResumeCallback) -> None:
        try:
            await asyncio.sleep(timeout)
            decision = "approve" if behavior == "allow" else "reject"
            feedback = f"Auto-{'approved' if decision == 'approve' else 'rejected'}: approval timeout ({timeout:.0f}s)"
            resume_value: dict[str, object] = {
                "decision": decision,
                "feedback": feedback,
            }
            logger.warning("Approval timeout fired: key=%s, auto-%s after %ss", key, decision, timeout)
            _record_timeout_audit(key, decision, timeout)
            await callback(resume_value)
        except asyncio.CancelledError:
            logger.debug("Approval timeout cancelled (manual resume): key=%s", key)
        except Exception:
            logger.exception("Approval timeout callback failed: key=%s", key)
        finally:
            self._tasks.pop(key, None)

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
        return count

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())


def _record_timeout_audit(key: str, decision: str, timeout: float) -> None:
    """Record the timeout auto-decision to the security audit trail."""
    try:
        from myrm_agent_harness.agent.security.audit import record_decision

        kind = "TIMEOUT_APPROVED" if decision == "approve" else "TIMEOUT_DENIED"
        record_decision(
            tool_name="approval_timeout",
            decision=kind,
            reason=f"Auto-{'approved' if decision == 'approve' else 'rejected'} after {timeout:.0f}s timeout (key={key})",
        )
    except Exception:
        logger.debug("Could not record timeout audit for key=%s", key)
