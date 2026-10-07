"""Bi-directional agent channel gateway for active peer-to-peer collaboration.

Manages bidirectional communication channels between collaborating agents with
TTL window expiration, message frames queuing, delivery receipts, and protocol prompts.

[INPUT]
- runtime.context.agent_mention_types::BidiChannelLink, PeerMessageFrame (POS: Agent mention dual-mode
  interaction types and communication contracts.)

[OUTPUT]
- BidiAgentChannelGateway: Gateway orchestrating bidirectional peer-to-peer message exchanges across agent
  sessions.

[POS]
Bi-directional agent channel gateway for active peer-to-peer collaboration.
"""

from __future__ import annotations

import time
import uuid

from .agent_mention_types import BidiChannelLink, PeerMessageFrame


class BidiAgentChannelGateway:
    """Gateway orchestrating bidirectional peer-to-peer message exchanges across agent sessions."""

    def __init__(self, default_ttl_seconds: float = 172800.0) -> None:  # Default 48h TTL
        self._default_ttl = default_ttl_seconds
        self._channels: dict[str, BidiChannelLink] = {}
        self._session_channel_map: dict[tuple[str, str], str] = {}
        self._message_inboxes: dict[str, list[PeerMessageFrame]] = {}

    def open_channel(
        self,
        session_a: str,
        session_b: str,
        ttl_seconds: float | None = None,
    ) -> BidiChannelLink:
        """Opens or reuses an active bidirectional communication channel between two sessions."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        pair_key = tuple(sorted([session_a, session_b]))

        # Return existing active channel if not expired
        existing_id = self._session_channel_map.get(pair_key)  # type: ignore[arg-type]
        now = time.time()
        if existing_id and existing_id in self._channels:
            link = self._channels[existing_id]
            if link.is_active and now < link.expires_at:
                return link

        channel_id = f"bidi_chan_{uuid.uuid4().hex[:12]}"
        new_link = BidiChannelLink(
            channel_id=channel_id,
            session_a=session_a,
            session_b=session_b,
            ttl_seconds=ttl,
            created_at=now,
            expires_at=now + ttl,
            is_active=True,
        )
        self._channels[channel_id] = new_link
        self._session_channel_map[pair_key] = channel_id  # type: ignore[index]
        self._message_inboxes[channel_id] = []
        return new_link

    def send_peer_message(
        self,
        channel_id: str,
        sender_session_id: str,
        payload: str,
    ) -> PeerMessageFrame:
        """Sends a message frame to the peer agent across an open channel."""
        if channel_id not in self._channels:
            raise KeyError(f"Bi-directional channel '{channel_id}' does not exist.")

        link = self._channels[channel_id]
        now = time.time()
        if not link.is_active or now >= link.expires_at:
            raise RuntimeError(f"Bi-directional channel '{channel_id}' has expired or is closed.")

        if sender_session_id not in (link.session_a, link.session_b):
            raise PermissionError(f"Session '{sender_session_id}' is not an authorized peer in this channel.")

        receiver_session_id = (
            link.session_b if sender_session_id == link.session_a else link.session_a
        )
        frame_id = f"frame_{uuid.uuid4().hex[:10]}"
        frame = PeerMessageFrame(
            frame_id=frame_id,
            channel_id=channel_id,
            sender_session_id=sender_session_id,
            receiver_session_id=receiver_session_id,
            payload=payload,
            timestamp=now,
            acknowledged=False,
        )
        self._message_inboxes[channel_id].append(frame)
        return frame

    def poll_peer_messages(
        self,
        channel_id: str,
        receiver_session_id: str,
        auto_acknowledge: bool = True,
    ) -> tuple[PeerMessageFrame, ...]:
        """Polls unread or pending message frames addressed to the receiver session."""
        if channel_id not in self._channels or channel_id not in self._message_inboxes:
            return ()

        frames = self._message_inboxes[channel_id]
        matched: list[PeerMessageFrame] = []
        updated: list[PeerMessageFrame] = []

        for f in frames:
            if f.receiver_session_id == receiver_session_id and not f.acknowledged:
                matched.append(f)
                if auto_acknowledge:
                    ack_frame = PeerMessageFrame(
                        frame_id=f.frame_id,
                        channel_id=f.channel_id,
                        sender_session_id=f.sender_session_id,
                        receiver_session_id=f.receiver_session_id,
                        payload=f.payload,
                        timestamp=f.timestamp,
                        acknowledged=True,
                    )
                    updated.append(ack_frame)
                else:
                    updated.append(f)
            else:
                updated.append(f)

        if auto_acknowledge:
            self._message_inboxes[channel_id] = updated

        return tuple(matched)

    def close_channel(self, channel_id: str) -> bool:
        """Explicitly closes an active bidirectional channel."""
        if channel_id not in self._channels:
            return False
        link = self._channels[channel_id]
        closed_link = BidiChannelLink(
            channel_id=link.channel_id,
            session_a=link.session_a,
            session_b=link.session_b,
            ttl_seconds=link.ttl_seconds,
            created_at=link.created_at,
            expires_at=link.expires_at,
            is_active=False,
        )
        self._channels[channel_id] = closed_link
        return True

    def build_bidi_channel_prompt(
        self,
        link: BidiChannelLink,
        peer_session_id: str,
        peer_label: str = "",
    ) -> str:
        """Constructs an instructional preamble informing the agent of the active peer channel."""
        label_desc = f" ({peer_label})" if peer_label else ""
        lines = [
            f"<bidi_agent_channel id='{link.channel_id}'>",
            f"Active Bi-directional Communication Channel established with peer session: {peer_session_id}{label_desc}",
            f"- Channel TTL: {int(link.ttl_seconds)}s (Expires in {int(max(0, link.expires_at - time.time()))}s)",
            "- Usage Instructions: You can exchange deliverables, queries, and status updates with this peer agent.",
            "- Tooling: Use `bidi_send_message` or `bidi_poll_messages` referencing this channel ID.",
            "</bidi_agent_channel>",
        ]
        return "\n".join(lines)
