"""Replay-safe approval round-trips of one delegation.

[INPUT]
- agent.sub_agents.checkpointer::delete_subagent_checkpoint (POS: Releases the checkpoint thread of a subagent that is abandoned while paused for approval.)
- agent.sub_agents.types::SubAgentResult, SubAgentStatus (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- delegation_task_id: Id of one delegation that survives the re-executions LangGraph runs after every UI approval
- approvals_unanswerable: Context in which no user can answer a subagent's approval request (parallel runs); ``settle`` declines such requests instead of interrupting
- ApprovalJournal, JournalRecord: Per-manager record of delegations that are waiting on UI approval
- ApprovalScope: One delegation's handle on the journal; ``settle`` drives a subagent through its approvals, ``remember`` pins a value computed on the first execution

[POS]
LangGraph re-runs the whole delegate_task call from its first line after every ``interrupt()``. The journal remembers
what earlier executions already did, so a replay walks past the approvals the user has answered without spawning or
resuming the subagent again, and acts only at the frontier where the next answer is still missing. The journal lives
in memory: when it is lost (restart, rebuilt agent) the checkpoint still holds the answers given to the lost subagent,
and a replacement subagent must not receive them. Where nobody can answer (tasks running in parallel), an approval
request ends the task with a readable failure instead of an interrupt.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import TypeVar, cast

from langgraph.config import get_config
from langgraph.errors import GraphInterrupt

from myrm_agent_harness.agent.sub_agents.checkpointer import delete_subagent_checkpoint
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_T = TypeVar("_T")

SpawnResult = SubAgentResult | dict[str, object]
SpawnStep = Callable[[], Awaitable[SpawnResult]]
ResumeStep = Callable[[object], Awaitable[SpawnResult]]
AskUser = Callable[[SubAgentResult], object]
ThreadCleaner = Callable[[str], Awaitable[None]]

_UNANSWERABLE: ContextVar[bool] = ContextVar("subagent_approvals_unanswerable", default=False)

_DECLINED = (
    "This task needs the user's approval, which cannot be requested while tasks run in parallel. "
    "Delegate it on its own and wait for its result so the approval can be shown."
)


@contextmanager
def approvals_unanswerable() -> Iterator[None]:
    """Mark the delegations started inside as unable to reach the user.

    An interrupt raised by one of several concurrent tasks cannot be shown: the gathering code swallows it and
    runs outside the graph for swarm fission. Declining the request keeps the other tasks' results usable.
    """
    token = _UNANSWERABLE.set(True)
    try:
        yield
    finally:
        _UNANSWERABLE.reset(token)


def delegation_task_id(payload_hash: str) -> str:
    """Id of one delegation, identical across the re-executions that follow each UI approval.

    The tool call's checkpoint namespace is the same on every re-execution of that call and differs between
    calls, so together with the call fingerprint it names the delegation without any extra tool parameter.
    Outside a graph run nothing is re-executed and a random id is enough.
    """
    try:
        namespace = get_config().get("configurable", {}).get("checkpoint_ns")
    except RuntimeError:
        namespace = None
    if not namespace:
        return uuid.uuid4().hex[:8]
    return hashlib.sha256(f"{namespace}\0{payload_hash}".encode()).hexdigest()[:8]


@dataclass(slots=True)
class JournalRecord:
    """What the executions of one delegation have done so far."""

    steps: list[SpawnResult] = field(default_factory=list)
    pinned: dict[str, object] = field(default_factory=dict)
    stale_answers: int = 0
    """Answers the checkpoint already held when the current subagent first asked: they belong to a lost subagent."""


class ApprovalJournal:
    """Delegations waiting on UI approval, keyed by task id.

    ``discard_stale_thread`` drops the checkpoint thread an earlier process left under a delegation's id; it is
    what keeps a replacement subagent from inheriting the conversation of the one the journal has lost.
    """

    def __init__(self, *, discard_stale_thread: ThreadCleaner | None = None) -> None:
        self._records: dict[str, JournalRecord] = {}
        self._discard_stale_thread = discard_stale_thread

    def is_replay(self, task_id: str) -> bool:
        """True when an earlier execution of this delegation has left a record, i.e. this call is its replay."""
        return task_id in self._records

    def scope(self, task_id: str, *, resume: ResumeStep, ask: AskUser) -> ApprovalScope:
        """Bind the journal to one delegation.

        ``ask`` hands a paused subagent's request to the user and returns their decision; on a replay it returns
        the stored decision of an already answered request, and it raises (``interrupt()``) while none is stored.
        ``resume`` continues the subagent with a decision.
        """
        return ApprovalScope(self, task_id, resume=resume, ask=ask)

    def record(self, task_id: str) -> JournalRecord:
        """The delegation's record, created on first use (``ApprovalScope`` is the only caller)."""
        return self._records.setdefault(task_id, JournalRecord())

    def discard(self, task_id: str) -> None:
        """Forget a delegation that finished or failed (``ApprovalScope`` is the only caller)."""
        self._records.pop(task_id, None)

    async def clear_stale_thread(self, task_id: str) -> None:
        """Start a delegation's subagent from an empty thread (``ApprovalScope`` is the only caller)."""
        if self._discard_stale_thread is not None:
            await self._discard_stale_thread(task_id)


class ApprovalScope:
    """One delegation's view of the journal."""

    __slots__ = ("_ask", "_journal", "_resume", "_task_id")

    def __init__(self, journal: ApprovalJournal, task_id: str, *, resume: ResumeStep, ask: AskUser) -> None:
        self._journal = journal
        self._task_id = task_id
        self._resume = resume
        self._ask = ask

    def remember(self, key: str, make: Callable[[], _T]) -> _T:
        """Compute a value on the first execution and hand the same value to every replay."""
        pinned = self._journal.record(self._task_id).pinned
        if key not in pinned:
            pinned[key] = make()
        return cast("_T", pinned[key])

    async def settle(self, spawn: SpawnStep) -> SpawnResult:
        """Run ``spawn`` and carry the subagent through every approval request it raises.

        The first answered requests of a replay come straight from the journal; only the step after the last
        recorded one spawns or resumes. Finishing or failing ends the delegation and drops its record; a request
        still waiting on the user (``GraphInterrupt``) keeps the record for the next execution.
        """
        try:
            result = await self._advance(self._journal.record(self._task_id), spawn)
        except GraphInterrupt:
            raise
        except BaseException:
            self._journal.discard(self._task_id)
            raise
        self._journal.discard(self._task_id)
        return result

    async def _advance(self, record: JournalRecord, spawn: SpawnStep) -> SpawnResult:
        spawned_now = not record.steps
        if spawned_now:
            await self._journal.clear_stale_thread(self._task_id)
            record.steps.append(await spawn())
        result = record.steps[0]
        answered = 0
        stale_to_skip = record.stale_answers
        while isinstance(result, SubAgentResult) and result.status == SubAgentStatus.PENDING_APPROVAL:
            if _UNANSWERABLE.get():
                return await _decline(result)
            decisions = self._ask(result)
            if spawned_now:
                # A subagent that has just been spawned has not been answered yet, so this answer was given for a
                # subagent the journal no longer knows; the user is asked again about the new request.
                record.stale_answers += 1
                logger.warning("Discarded an approval given before subagent %s asked anything", self._task_id)
                continue
            if stale_to_skip:
                stale_to_skip -= 1
                continue
            answered += 1
            if answered == len(record.steps):
                logger.info("Resuming subagent %s after UI approval", self._task_id)
                record.steps.append(await self._resume(decisions))
            result = record.steps[answered]
        return result


async def _decline(paused: SubAgentResult) -> SubAgentResult:
    """End a paused subagent whose approval request nobody can answer, and free its checkpoint thread."""
    logger.warning("Subagent %s asked for approval in a run without a user to answer; declined", paused.task_id)
    await delete_subagent_checkpoint(paused.task_id)
    return replace(paused, success=False, status=SubAgentStatus.BLOCKED, error=_DECLINED, payload=None)
