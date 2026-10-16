"""Replay-safe approval round-trips of one delegation.

[INPUT]
- agent.sub_agents.types::SubAgentResult, SubAgentStatus (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- delegation_task_id: Id of one delegation that survives the re-executions LangGraph runs after every UI approval
- ApprovalJournal, JournalRecord: Per-manager record of delegations that are waiting on UI approval
- ApprovalScope: One delegation's handle on the journal; ``settle`` drives a subagent through its approvals, ``remember`` pins a value computed on the first execution

[POS]
LangGraph re-runs the whole delegate_task call from its first line after every ``interrupt()``. The journal remembers
what earlier executions already did, so a replay walks past the approvals the user has answered without spawning or
resuming the subagent again, and acts only at the frontier where the next answer is still missing.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar, cast

from langgraph.config import get_config
from langgraph.errors import GraphInterrupt

from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_T = TypeVar("_T")

SpawnResult = SubAgentResult | dict[str, object]
SpawnStep = Callable[[], Awaitable[SpawnResult]]
ResumeStep = Callable[[object], Awaitable[SpawnResult]]
AskUser = Callable[[SubAgentResult], object]


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


class ApprovalJournal:
    """Delegations waiting on UI approval, keyed by task id."""

    def __init__(self) -> None:
        self._records: dict[str, JournalRecord] = {}

    def is_replay(self, task_id: str) -> bool:
        """True when an earlier execution of this delegation has left a record, i.e. this call is its replay."""
        return task_id in self._records

    def scope(self, task_id: str, *, resume: ResumeStep, ask: AskUser) -> ApprovalScope:
        """Bind the journal to one delegation.

        ``ask`` hands a paused subagent's request to the user and returns their decision; on a replay it returns
        the stored decision of an already answered request. ``resume`` continues the subagent with a decision.
        """
        return ApprovalScope(self, task_id, resume=resume, ask=ask)

    def record(self, task_id: str) -> JournalRecord:
        """The delegation's record, created on first use (``ApprovalScope`` is the only caller)."""
        return self._records.setdefault(task_id, JournalRecord())

    def discard(self, task_id: str) -> None:
        """Forget a delegation that finished or failed (``ApprovalScope`` is the only caller)."""
        self._records.pop(task_id, None)


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
        if not record.steps:
            record.steps.append(await spawn())
        result = record.steps[0]
        answered = 0
        while isinstance(result, SubAgentResult) and result.status == SubAgentStatus.PENDING_APPROVAL:
            decisions = self._ask(result)
            answered += 1
            if answered == len(record.steps):
                logger.info("Resuming subagent %s after UI approval", self._task_id)
                record.steps.append(await self._resume(decisions))
            result = record.steps[answered]
        return result
