"""Agent mention dual-mode router coordinating read-only snapshots and bidi channels.

Parses and normalizes @ agent mentions, arbitrates collaborative intents,
injects read-only context snapshots without disturbing target agents,
and establishes live bidirectional peer-to-peer communication channels.

[INPUT]
- runtime.context.agent_mention_types::AgentMentionMode, MentionProcessingAudit, NormalizedAgentMention
  (POS: Agent mention dual-mode interaction types and communication contracts.)
- runtime.context.bidi_agent_channel_gateway::BidiAgentChannelGateway (POS: Bi-directional agent channel
  gateway for active peer-to-peer collaboration.)
- runtime.context.project_hierarchy_session_types::ArchivedMessageEntry (POS: Project hierarchy session
  archive and keyword resurrection types.)
- runtime.context.read_only_snapshot_capturer::ReadOnlySnapshotCapturer (POS: Read-only context snapshot
  capturer for non-intrusive peer agent inspection.)

[OUTPUT]
- AgentMentionDualModeRouter: Orchestrates dual-mode mention parsing, routing, snapshot injection, and
  channel establishment.

[POS]
Agent mention dual-mode router coordinating read-only snapshots and bidi channels.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from .agent_mention_types import (
    AgentMentionMode,
    MentionProcessingAudit,
    NormalizedAgentMention,
)
from .bidi_agent_channel_gateway import BidiAgentChannelGateway
from .project_hierarchy_session_types import ArchivedMessageEntry
from .read_only_snapshot_capturer import ReadOnlySnapshotCapturer

# Signature for retrieving historical messages for a given session ID
MessageFetchProvider = Callable[[str], Sequence[ArchivedMessageEntry]]


class AgentMentionDualModeRouter:
    """Orchestrates dual-mode mention parsing, routing, snapshot injection, and channel establishment."""

    def __init__(
        self,
        snapshot_capturer: ReadOnlySnapshotCapturer | None = None,
        channel_gateway: BidiAgentChannelGateway | None = None,
        message_provider: MessageFetchProvider | None = None,
    ) -> None:
        self._capturer = snapshot_capturer or ReadOnlySnapshotCapturer()
        self._gateway = channel_gateway or BidiAgentChannelGateway()
        self._message_provider = message_provider

    @property
    def gateway(self) -> BidiAgentChannelGateway:
        """Underlying bidirectional channel gateway."""
        return self._gateway

    @property
    def capturer(self) -> ReadOnlySnapshotCapturer:
        """Underlying read-only snapshot capturer."""
        return self._capturer

    def normalize_mentions(
        self,
        explicit_mentions: Sequence[NormalizedAgentMention] | None,
        prompt_text: str = "",
    ) -> tuple[NormalizedAgentMention, ...]:
        """Normalizes and deduplicates mentions from explicit inputs and text markers."""
        mention_map: dict[str, NormalizedAgentMention] = {}

        if explicit_mentions:
            for m in explicit_mentions:
                target_id = m.target_session_id.strip()
                if not target_id:
                    continue
                # If already present, BIDIRECTIONAL takes precedence
                if target_id in mention_map:
                    if m.mode == AgentMentionMode.BIDIRECTIONAL:
                        mention_map[target_id] = m
                else:
                    mention_map[target_id] = m

        # Extract mentions embedded directly in prompt text: @session=<id> or session=<id>
        extracted_matches = re.findall(
            r"(?:^|[\s(@])@?(?:session|agent)=([A-Za-z0-9_-]{4,128})",
            prompt_text,
        )
        for s_id in extracted_matches:
            target_id = s_id.strip()
            # Default to READ_ONLY for copied text IDs unless explicitly selected
            if target_id not in mention_map:
                mention_map[target_id] = NormalizedAgentMention(
                    target_session_id=target_id,
                    mode=AgentMentionMode.READ_ONLY,
                    mention_label=target_id,
                )

        return tuple(mention_map.values())

    def route_and_apply(
        self,
        current_session_id: str,
        prompt_text: str,
        mentions: Sequence[NormalizedAgentMention],
        workspace_path: str = "",
    ) -> tuple[str, MentionProcessingAudit]:
        """Routes dual-mode mentions into enhanced prompt and yields execution audit."""
        if not mentions:
            return prompt_text, MentionProcessingAudit(
                total_mentions=0,
                read_only_injected=0,
                bidi_channels_linked=0,
                bidi_channels_rejected=0,
                captured_tokens_approx=0,
            )

        read_only_blocks: list[str] = []
        bidi_blocks: list[str] = []
        ro_count = 0
        bidi_linked_count = 0
        bidi_rejected_count = 0
        approx_tokens = 0

        for m in mentions:
            target_id = m.target_session_id
            if target_id == current_session_id:
                continue

            if m.mode == AgentMentionMode.READ_ONLY:
                # Capture read-only snapshot
                history = self._message_provider(target_id) if self._message_provider else ()
                snapshot = self._capturer.capture_snapshot(
                    source_session_id=current_session_id,
                    target_session_id=target_id,
                    messages=history,
                    workspace_path=workspace_path,
                )
                block = self._capturer.format_mention_prompt_block(snapshot)
                read_only_blocks.append(block)
                ro_count += 1
                approx_tokens += len(block) // 4

            elif m.mode == AgentMentionMode.BIDIRECTIONAL:
                try:
                    channel_link = self._gateway.open_channel(
                        session_a=current_session_id,
                        session_b=target_id,
                    )
                    bidi_prompt = self._gateway.build_bidi_channel_prompt(
                        link=channel_link,
                        peer_session_id=target_id,
                        peer_label=m.mention_label,
                    )
                    bidi_blocks.append(bidi_prompt)
                    bidi_linked_count += 1
                    approx_tokens += len(bidi_prompt) // 4
                except Exception:
                    bidi_rejected_count += 1

        # Compose output prompt: Read-only references injected before/with prompt; bidi offer appended at end
        composed_parts = [prompt_text]
        if read_only_blocks:
            composed_parts.extend(read_only_blocks)
        if bidi_blocks:
            composed_parts.extend(bidi_blocks)

        final_prompt = "\n\n".join(composed_parts)
        audit = MentionProcessingAudit(
            total_mentions=len(mentions),
            read_only_injected=ro_count,
            bidi_channels_linked=bidi_linked_count,
            bidi_channels_rejected=bidi_rejected_count,
            captured_tokens_approx=approx_tokens,
        )
        return final_prompt, audit
