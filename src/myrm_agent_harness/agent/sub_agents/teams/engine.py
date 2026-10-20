"""Durable Agent Team Engine coordinating Roster, CAS Task Graph, and Peer Mailbox.

[INPUT]
- .types::(TeamMemberPhase, TeamMemberRole, TeamMemberSnapshot,
           TeamMessageSnapshot, TeamProjection, TeamTaskView, DeliveryMode)
- .task_graph::TaskGraphEngine
- .mailbox::DurablePeerMailbox

[OUTPUT]
- DurableAgentTeamEngine: implicit root lead, kebab-case teammate spawning, CAS task flow,
  durable peer messaging, and edge-triggered change observation

[POS]
Core runtime facade for topic_12 #28 Durable Agent Teams.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

from .mailbox import DurablePeerMailbox
from .task_graph import TaskGraphEngine
from .types import (
    DeliveryMode,
    TeamMemberPhase,
    TeamMemberRole,
    TeamMemberSnapshot,
    TeamMessageSnapshot,
    TeamProjection,
    TeamTaskStatus,
    TeamTaskView,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

_KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class DurableAgentTeamEngine:
    """Session-scoped multi-agent durable team orchestration engine."""

    def __init__(self, team_id: str, workspace_path: str | None = None) -> None:
        self.team_id = team_id
        self.workspace_path = workspace_path
        self._members: dict[str, TeamMemberSnapshot] = {}
        self._task_graph = TaskGraphEngine(team_id=team_id)
        self._mailbox = DurablePeerMailbox(team_id=team_id, workspace_path=workspace_path)
        self._change_event = asyncio.Event()
        self._failure: str | None = None

        # Automatically provision the implicit root Team Lead
        now = time.time()
        self._members["lead"] = TeamMemberSnapshot(
            id=f"{team_id}-lead",
            name="lead",
            description="Implicit Root Session Team Lead",
            provider="host",
            context="fork",
            role=TeamMemberRole.LEAD,
            phase=TeamMemberPhase.ACTIVE,
            created_at=now,
        )

    # -------------------------------------------------------------------------
    # Roster Management
    # -------------------------------------------------------------------------

    def spawn_teammate(
        self,
        name: str,
        description: str,
        provider: str = "default",
        context: str = "fresh",
    ) -> TeamMemberSnapshot:
        """Spawn and register a named durable teammate with kebab-case validation."""
        cleaned_name = name.strip()
        if not _KEBAB_CASE_PATTERN.match(cleaned_name):
            raise ValueError(
                f"Invalid teammate name '{name}'. Must be kebab-case (e.g., 'researcher-alpha')"
            )

        if cleaned_name in self._members:
            raise ValueError(f"Teammate with name '{cleaned_name}' already exists in team {self.team_id}")

        member_id = f"{self.team_id}-{cleaned_name}"
        now = time.time()

        snapshot = TeamMemberSnapshot(
            id=member_id,
            name=cleaned_name,
            description=description,
            provider=provider,
            context=context,
            role=TeamMemberRole.TEAMMATE,
            phase=TeamMemberPhase.ACTIVE,
            created_at=now,
        )
        self._members[cleaned_name] = snapshot
        self._notify_change()
        return snapshot

    def fail_teammate(self, name: str, error: str) -> TeamMemberSnapshot:
        """Mark a teammate as failed with diagnostic reason."""
        cleaned_name = name.strip().lower()
        member = self._members.get(cleaned_name)
        if member is None:
            raise KeyError(f"Teammate '{cleaned_name}' not found in team {self.team_id}")

        failed_member = TeamMemberSnapshot(
            id=member.id,
            name=member.name,
            description=member.description,
            provider=member.provider,
            context=member.context,
            role=member.role,
            phase=TeamMemberPhase.FAILED,
            error=error,
            created_at=member.created_at,
        )
        self._members[cleaned_name] = failed_member
        self._failure = f"Teammate '{cleaned_name}' failed: {error}"
        self._notify_change()
        return failed_member

    def get_member(self, name: str) -> TeamMemberSnapshot | None:
        return self._members.get(name.strip().lower())

    def list_members(self) -> list[TeamMemberSnapshot]:
        return list(self._members.values())

    # -------------------------------------------------------------------------
    # CAS Task Graph Facade
    # -------------------------------------------------------------------------

    def create_task(
        self,
        subject: str,
        description: str = "",
        blocked_by: Sequence[str] = (),
        write_scopes: Sequence[str] = (),
        owner_name: str | None = None,
    ) -> TeamTaskView:
        owner_id = None
        if owner_name:
            member = self.get_member(owner_name)
            if member is None:
                raise KeyError(f"Owner teammate '{owner_name}' does not exist in roster")
            owner_id = member.id

        view = self._task_graph.create_task(
            subject=subject,
            description=description,
            blocked_by=blocked_by,
            write_scopes=write_scopes,
            owner_id=owner_id,
            owner_name=owner_name,
        )
        self._notify_change()
        return view

    def claim_task(
        self,
        task_id: str,
        expected_revision: int,
        owner_name: str,
    ) -> TeamTaskView:
        member = self.get_member(owner_name)
        if member is None:
            raise KeyError(f"Claimant teammate '{owner_name}' does not exist in roster")
        if member.phase != TeamMemberPhase.ACTIVE:
            raise RuntimeError(f"Cannot claim task: member '{owner_name}' is in phase '{member.phase.value}'")

        view = self._task_graph.claim_task(
            task_id=task_id,
            expected_revision=expected_revision,
            owner_id=member.id,
            owner_name=member.name,
        )
        self._notify_change()
        return view

    def complete_task(self, task_id: str, expected_revision: int) -> TeamTaskView:
        view = self._task_graph.complete_task(task_id=task_id, expected_revision=expected_revision)
        self._notify_change()
        return view

    def update_task(
        self,
        task_id: str,
        expected_revision: int,
        subject: str | None = None,
        description: str | None = None,
        status: TeamTaskStatus | None = None,
        owner_name: str | None = None,
        blocked_by: Sequence[str] | None = None,
        write_scopes: Sequence[str] | None = None,
    ) -> TeamTaskView:
        owner_id = None
        if owner_name is not None:
            member = self.get_member(owner_name)
            if member is None:
                raise KeyError(f"Owner teammate '{owner_name}' not found")
            owner_id = member.id

        view = self._task_graph.update_task(
            task_id=task_id,
            expected_revision=expected_revision,
            subject=subject,
            description=description,
            status=status,
            owner_id=owner_id,
            owner_name=owner_name,
            blocked_by=blocked_by,
            write_scopes=write_scopes,
        )
        self._notify_change()
        return view

    def list_tasks(self, include_deleted: bool = False) -> list[TeamTaskView]:
        return self._task_graph.list_tasks(include_deleted=include_deleted)

    def get_task(self, task_id: str) -> TeamTaskView:
        return self._task_graph.get_task(task_id=task_id)

    # -------------------------------------------------------------------------
    # Peer Mailbox Facade
    # -------------------------------------------------------------------------

    def send_peer_message(
        self,
        sender_name: str,
        target_name: str,
        content: str,
        mode: DeliveryMode = DeliveryMode.QUIET,
    ) -> TeamMessageSnapshot:
        sender = self.get_member(sender_name)
        if sender is None:
            raise KeyError(f"Sender teammate '{sender_name}' not registered in team")
        target = self.get_member(target_name)
        if target is None:
            raise KeyError(f"Target teammate '{target_name}' not registered in team")

        msg = self._mailbox.send_peer_message(
            sender_id=sender.id,
            sender_name=sender.name,
            target_id=target.id,
            target_name=target.name,
            content=content,
            mode=mode,
        )
        self._notify_change()
        return msg

    def drain_inbox(self, member_name: str) -> list[TeamMessageSnapshot]:
        member = self.get_member(member_name)
        if member is None:
            raise KeyError(f"Member '{member_name}' not registered in team")
        return self._mailbox.drain_inbox(target_id=member.id)

    def list_message_history(self, limit: int = 100) -> list[dict[str, object]]:
        return self._mailbox.list_history(limit=limit)

    # -------------------------------------------------------------------------
    # Projection & Observation
    # -------------------------------------------------------------------------

    def get_projection(self) -> TeamProjection:
        """Return the complete durable projection for callers and web UI."""
        return TeamProjection(
            team_id=self.team_id,
            members=tuple(self._members.values()),
            tasks=tuple(self._task_graph.list_tasks()),
            failure=self._failure,
        )

    async def wait_for_change(self, timeout_sec: float = 10.0) -> bool:
        """Wait for the next team domain event or timeout."""
        self._change_event.clear()
        try:
            await asyncio.wait_for(self._change_event.wait(), timeout=timeout_sec)
            return True
        except TimeoutError:
            return False

    def _notify_change(self) -> None:
        self._change_event.set()
