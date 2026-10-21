"""P2P Agent Socket Mesh Node implementing atomic envelope protocol and anti-loop guards.

[INPUT]
- __future__
- asyncio
- os
- time
- uuid
- typing

[OUTPUT]
- SocketMeshNode

[POS]
P2P Agent Socket Mesh Node implementing atomic envelope protocol and anti-loop guards.

"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import ClassVar

from .mesh_registry import MeshRegistry
from .types import (
    AgentCard,
    Envelope,
    EnvelopeType,
    MeshDispatchResult,
    PeerStatus,
    RegistryEntry,
)


class SocketMeshNode:
    """A decentralized P2P communication node representing an active agent.

    Provides high-speed zero-broker messaging with:
    - Standard atomic envelopes (prompt, response, ping, pong)
    - Anti-loop hop counter prevention (hops <= MAX_HOPS)
    - In-flight pending reply futures (coms_await)
    - Telemetry heartbeat updating
    """

    MAX_HOPS: int = 5
    DEFAULT_TIMEOUT: float = 30.0

    # In-process node routing table for zero-latency co-located agents
    _active_nodes: ClassVar[dict[str, SocketMeshNode]] = {}

    def __init__(
        self,
        name: str,
        project: str = "default",
        session_id: str | None = None,
        purpose: str = "General Task Agent",
        model: str = "default-model",
        registry: MeshRegistry | None = None,
    ) -> None:
        self.name = name.strip()
        self.project = project.strip()
        self.session_id = session_id or str(uuid.uuid4())
        self.purpose = purpose
        self.model = model
        self.registry = registry or MeshRegistry()

        self.endpoint = self.registry.get_endpoint(self.session_id)
        self.pid = os.getpid()
        self.cwd = os.getcwd()

        self.context_used_pct = 0.0
        self.queue_depth = 0
        self.is_running = False

        self._pending_replies: dict[str, asyncio.Future[Envelope]] = {}
        self._inbound_messages: list[Envelope] = []
        self._audit_logs: list[dict[str, object]] = []

    def start(self) -> None:
        """Register node in filesystem registry and activate in-process routing."""
        entry = RegistryEntry(
            session_id=self.session_id,
            name=self.name,
            purpose=self.purpose,
            model=self.model,
            pid=self.pid,
            endpoint=self.endpoint,
            cwd=self.cwd,
            started_at=time.time(),
            heartbeat_at=time.time(),
            context_used_pct=self.context_used_pct,
            queue_depth=self.queue_depth,
            status=PeerStatus.ONLINE,
        )
        self.registry.register_peer(self.project, entry)
        route_key = f"{self.project}:{self.name}"
        SocketMeshNode._active_nodes[route_key] = self
        self.is_running = True
        self._log_audit("NODE_STARTED", f"Node '{self.name}' active on project '{self.project}'")

    def stop(self) -> None:
        """Unregister node and clean up pending futures."""
        self.is_running = False
        route_key = f"{self.project}:{self.name}"
        SocketMeshNode._active_nodes.pop(route_key, None)
        self.registry.unregister_peer(self.project, self.name)

        # Cancel any pending replies
        for fut in self._pending_replies.values():
            if not fut.done():
                fut.cancel()
        self._pending_replies.clear()
        self._log_audit("NODE_STOPPED", f"Node '{self.name}' stopped and unregistered.")

    def coms_list(self, auto_mark_stale: bool = True) -> list[RegistryEntry]:
        """Tool primitive: list all registered peers in the current project mesh."""
        return self.registry.list_peers(self.project, auto_mark_stale=auto_mark_stale)

    async def coms_send(
        self,
        target_name: str,
        prompt: str,
        timeout_seconds: float = DEFAULT_TIMEOUT,
    ) -> MeshDispatchResult:
        """Tool primitive: asynchronously dispatch a prompt envelope to a peer."""
        start_time = time.time()
        target_peer = self.registry.get_peer(self.project, target_name)
        if not target_peer:
            return MeshDispatchResult(
                success=False,
                msg_id="",
                error=f"Peer '{target_name}' not found in project '{self.project}'.",
            )

        msg_id = str(uuid.uuid4())
        envelope = Envelope(
            msg_id=msg_id,
            type=EnvelopeType.PROMPT,
            sender_session=self.session_id,
            sender_name=self.name,
            sender_endpoint=self.endpoint,
            target_name=target_name,
            hops=0,
            timestamp=start_time,
            prompt=prompt,
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Envelope] = loop.create_future()
        self._pending_replies[msg_id] = future

        self._log_audit("SEND_PROMPT", f"Sending prompt {msg_id} to '{target_name}'")
        delivered = await self._deliver_envelope(envelope)

        if not delivered:
            self._pending_replies.pop(msg_id, None)
            return MeshDispatchResult(
                success=False,
                msg_id=msg_id,
                error=f"Failed to deliver envelope {msg_id} to '{target_name}'. Target offline or unreachable.",
            )

        duration = (time.time() - start_time) * 1000
        return MeshDispatchResult(
            success=True,
            msg_id=msg_id,
            hops=0,
            duration_ms=duration,
        )

    async def coms_await(
        self,
        msg_id: str,
        timeout_seconds: float = DEFAULT_TIMEOUT,
    ) -> MeshDispatchResult:
        """Tool primitive: wait for a response envelope for a previously dispatched message."""
        start_time = time.time()
        future = self._pending_replies.get(msg_id)
        if not future:
            return MeshDispatchResult(
                success=False,
                msg_id=msg_id,
                error=f"No pending await tracking for msg_id '{msg_id}'.",
            )

        try:
            reply_envelope = await asyncio.wait_for(future, timeout=timeout_seconds)
            self._pending_replies.pop(msg_id, None)
            duration = (time.time() - start_time) * 1000

            if reply_envelope.error:
                return MeshDispatchResult(
                    success=False,
                    msg_id=msg_id,
                    error=reply_envelope.error,
                    hops=reply_envelope.hops,
                    duration_ms=duration,
                )

            return MeshDispatchResult(
                success=True,
                msg_id=msg_id,
                response=reply_envelope.response,
                hops=reply_envelope.hops,
                duration_ms=duration,
            )
        except TimeoutError:
            self._pending_replies.pop(msg_id, None)
            return MeshDispatchResult(
                success=False,
                msg_id=msg_id,
                error=f"Await timed out after {timeout_seconds}s waiting for msg_id '{msg_id}'.",
                duration_ms=(time.time() - start_time) * 1000,
            )

    async def coms_reply(
        self,
        inbound_envelope: Envelope,
        response_text: str,
        error: str | None = None,
    ) -> MeshDispatchResult:
        """Send a response envelope back to the original sender."""
        next_hops = inbound_envelope.hops + 1
        if next_hops > self.MAX_HOPS:
            err_msg = f"Hop limit exceeded ({next_hops} > {self.MAX_HOPS}). Anti-loop triggered."
            self._log_audit("HOP_LIMIT_REJECT", err_msg)
            return MeshDispatchResult(success=False, msg_id=inbound_envelope.msg_id, error=err_msg, hops=next_hops)

        reply_envelope = Envelope(
            msg_id=inbound_envelope.msg_id,
            type=EnvelopeType.RESPONSE,
            sender_session=self.session_id,
            sender_name=self.name,
            sender_endpoint=self.endpoint,
            target_name=inbound_envelope.sender_name,
            hops=next_hops,
            timestamp=time.time(),
            response=response_text if not error else None,
            error=error,
        )

        delivered = await self._deliver_envelope(reply_envelope)
        return MeshDispatchResult(
            success=delivered,
            msg_id=inbound_envelope.msg_id,
            hops=next_hops,
            error=None if delivered else f"Failed to route reply to '{inbound_envelope.sender_name}'.",
        )

    async def coms_ping(
        self,
        target_name: str,
        timeout_seconds: float = 5.0,
    ) -> MeshDispatchResult:
        """Ping a peer to verify connectivity and obtain its live AgentCard."""
        start_time = time.time()
        msg_id = str(uuid.uuid4())
        ping_envelope = Envelope(
            msg_id=msg_id,
            type=EnvelopeType.PING,
            sender_session=self.session_id,
            sender_name=self.name,
            sender_endpoint=self.endpoint,
            target_name=target_name,
            hops=0,
            timestamp=start_time,
        )

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Envelope] = loop.create_future()
        self._pending_replies[msg_id] = future

        delivered = await self._deliver_envelope(ping_envelope)
        if not delivered:
            self._pending_replies.pop(msg_id, None)
            return MeshDispatchResult(success=False, msg_id=msg_id, error=f"Target '{target_name}' unreachable.")

        try:
            pong_envelope = await asyncio.wait_for(future, timeout=timeout_seconds)
            self._pending_replies.pop(msg_id, None)
            card_desc = pong_envelope.agent_card.purpose if pong_envelope.agent_card else "Active"
            return MeshDispatchResult(
                success=True,
                msg_id=msg_id,
                response=f"PONG from {target_name}: {card_desc}",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except TimeoutError:
            self._pending_replies.pop(msg_id, None)
            return MeshDispatchResult(success=False, msg_id=msg_id, error=f"Ping timeout ({timeout_seconds}s)")

    async def receive_envelope(self, envelope: Envelope) -> None:
        """Internal callback when an envelope arrives at this node."""
        if envelope.hops > self.MAX_HOPS:
            self._log_audit("HOP_LIMIT_REJECT", f"Envelope {envelope.msg_id} exceeded max hops: {envelope.hops}")
            return

        self._inbound_messages.append(envelope)

        # If it's a response or pong to a pending query, fulfill the future
        if envelope.type in (EnvelopeType.RESPONSE, EnvelopeType.PONG):
            fut = self._pending_replies.get(envelope.msg_id)
            if fut and not fut.done():
                fut.set_result(envelope)
                return

        # If it's a ping, auto reply with pong containing AgentCard
        if envelope.type == EnvelopeType.PING:
            card = AgentCard(
                name=self.name,
                purpose=self.purpose,
                model=self.model,
                pid=self.pid,
                endpoint=self.endpoint,
                cwd=self.cwd,
                context_used_pct=self.context_used_pct,
                queue_depth=self.queue_depth,
                status=PeerStatus.ONLINE,
            )
            pong = Envelope(
                msg_id=envelope.msg_id,
                type=EnvelopeType.PONG,
                sender_session=self.session_id,
                sender_name=self.name,
                sender_endpoint=self.endpoint,
                target_name=envelope.sender_name,
                hops=envelope.hops + 1,
                agent_card=card,
            )
            await self._deliver_envelope(pong)

    async def _deliver_envelope(self, envelope: Envelope) -> bool:
        """Route envelope to the target node either in-process or via peer handle."""
        target_name = envelope.target_name
        if not target_name:
            return False

        route_key = f"{self.project}:{target_name}"
        target_node = SocketMeshNode._active_nodes.get(route_key)
        if target_node and target_node.is_running:
            await target_node.receive_envelope(envelope)
            return True

        # Target not in active in-process registry table
        return False

    def get_audit_logs(self) -> list[dict[str, object]]:
        """Return chronological audit log of mesh operations."""
        return list(self._audit_logs)

    def _log_audit(self, event_type: str, detail: str) -> None:
        """Record an audit trail entry."""
        self._audit_logs.append({
            "timestamp": time.time(),
            "event_type": event_type,
            "node": self.name,
            "project": self.project,
            "detail": detail,
        })
