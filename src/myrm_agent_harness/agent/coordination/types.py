"""Teammate P2P message types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TeammateSendResult:
    accepted: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TeammateMessage:
    message_id: str
    session_id: str
    from_task_id: str
    to_task_id: str
    from_agent_type: str
    body: str
    created_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "from_task_id": self.from_task_id,
            "to_task_id": self.to_task_id,
            "from_agent_type": self.from_agent_type,
            "body": self.body,
            "created_at": self.created_at,
        }
