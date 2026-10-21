"""Types and data structures for the Lightweight P2P Agent Socket Mesh Protocol.

[INPUT]
- __future__
- time
- uuid
- dataclasses
- enum

[OUTPUT]
- EnvelopeType
- PeerStatus
- AgentCard
- RegistryEntry
- Envelope
- MeshDispatchResult

[POS]
Types and data structures for the Lightweight P2P Agent Socket Mesh Protocol.

"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class EnvelopeType(StrEnum):
    """Supported envelope types in the peer-to-peer mesh."""

    PROMPT = "prompt"
    RESPONSE = "response"
    PING = "ping"
    PONG = "pong"


class PeerStatus(StrEnum):
    """Operational health state of a peer in the registry."""

    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"


@dataclass
class AgentCard:
    """Card containing dynamic operational telemetry for an agent peer."""

    name: str = ""
    purpose: str = ""
    model: str = "default"
    pid: int = 0
    endpoint: str = ""
    cwd: str = ""
    context_used_pct: float = 0.0
    queue_depth: int = 0
    status: PeerStatus = PeerStatus.ONLINE

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "model": self.model,
            "pid": self.pid,
            "endpoint": self.endpoint,
            "cwd": self.cwd,
            "context_used_pct": self.context_used_pct,
            "queue_depth": self.queue_depth,
            "status": self.status.value,
        }


@dataclass
class RegistryEntry:
    """Persistent on-disk peer registration entry (~/.myrm/coms/projects/<project>/agents/<name>.json)."""

    session_id: str
    name: str
    purpose: str
    model: str
    pid: int
    endpoint: str
    cwd: str
    started_at: float = field(default_factory=time.time)
    heartbeat_at: float = field(default_factory=time.time)
    context_used_pct: float = 0.0
    queue_depth: int = 0
    status: PeerStatus = PeerStatus.ONLINE

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "purpose": self.purpose,
            "model": self.model,
            "pid": self.pid,
            "endpoint": self.endpoint,
            "cwd": self.cwd,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "context_used_pct": self.context_used_pct,
            "queue_depth": self.queue_depth,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RegistryEntry:
        return cls(
            session_id=str(data.get("session_id", "")),
            name=str(data.get("name", "")),
            purpose=str(data.get("purpose", "")),
            model=str(data.get("model", "")),
            pid=int(data.get("pid", 0)),  # type: ignore[arg-type]
            endpoint=str(data.get("endpoint", "")),
            cwd=str(data.get("cwd", "")),
            started_at=float(data.get("started_at", time.time())),  # type: ignore[arg-type]
            heartbeat_at=float(data.get("heartbeat_at", time.time())),  # type: ignore[arg-type]
            context_used_pct=float(data.get("context_used_pct", 0.0)),  # type: ignore[arg-type]
            queue_depth=int(data.get("queue_depth", 0)),  # type: ignore[arg-type]
            status=PeerStatus(str(data.get("status", "online"))),
        )


@dataclass
class Envelope:
    """Atomic standard envelope structure for P2P agent communication."""

    msg_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: EnvelopeType = EnvelopeType.PROMPT
    sender_session: str = ""
    sender_name: str = ""
    sender_endpoint: str = ""
    target_name: str | None = None
    hops: int = 0
    timestamp: float = field(default_factory=time.time)
    prompt: str | None = None
    response: str | None = None
    error: str | None = None
    agent_card: AgentCard | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "msg_id": self.msg_id,
            "type": self.type.value,
            "sender_session": self.sender_session,
            "sender_name": self.sender_name,
            "sender_endpoint": self.sender_endpoint,
            "hops": self.hops,
            "timestamp": self.timestamp,
        }
        if self.target_name is not None:
            d["target_name"] = self.target_name
        if self.prompt is not None:
            d["prompt"] = self.prompt
        if self.response is not None:
            d["response"] = self.response
        if self.error is not None:
            d["error"] = self.error
        if self.agent_card is not None:
            d["agent_card"] = self.agent_card.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Envelope:
        card: AgentCard | None = None
        if "agent_card" in data and isinstance(data["agent_card"], dict):
            c_data = data["agent_card"]
            card = AgentCard(
                name=str(c_data.get("name", "")),
                purpose=str(c_data.get("purpose", "")),
                model=str(c_data.get("model", "")),
                pid=int(c_data.get("pid", 0)),
                endpoint=str(c_data.get("endpoint", "")),
                cwd=str(c_data.get("cwd", "")),
                context_used_pct=float(c_data.get("context_used_pct", 0.0)),
                queue_depth=int(c_data.get("queue_depth", 0)),
                status=PeerStatus(str(c_data.get("status", "online"))),
            )
        return cls(
            msg_id=str(data.get("msg_id", str(uuid.uuid4()))),
            type=EnvelopeType(str(data.get("type", "prompt"))),
            sender_session=str(data.get("sender_session", "")),
            sender_name=str(data.get("sender_name", "")),
            sender_endpoint=str(data.get("sender_endpoint", "")),
            target_name=str(data["target_name"]) if "target_name" in data and data["target_name"] is not None else None,
            hops=int(data.get("hops", 0)),  # type: ignore[arg-type]
            timestamp=float(data.get("timestamp", time.time())),  # type: ignore[arg-type]
            prompt=str(data["prompt"]) if "prompt" in data and data["prompt"] is not None else None,
            response=str(data["response"]) if "response" in data and data["response"] is not None else None,
            error=str(data["error"]) if "error" in data and data["error"] is not None else None,
            agent_card=card,
        )


@dataclass
class MeshDispatchResult:
    """Result of dispatching a message or await query in the mesh."""

    success: bool
    msg_id: str
    error: str | None = None
    response: str | None = None
    hops: int = 0
    duration_ms: float = 0.0
