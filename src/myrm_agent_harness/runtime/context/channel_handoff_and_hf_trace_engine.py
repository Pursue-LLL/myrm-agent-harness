"""Cross-platform channel handoff coordinator and HuggingFace Trace exporter engine.

Provides native thread anchoring across Telegram, Discord, Slack, Feishu, and WeChat;
implements cryptographically verifiable session resumption; and exports standardized,
redacted HuggingFace Agent Trace Viewer JSONL streams.
"""

import hashlib
import json
import re
from datetime import UTC, datetime

from .channel_handoff_and_hf_trace_types import (
    ChannelThreadAnchorDescriptor,
    ChannelThreadKind,
    HandoffSessionEnvelope,
    HFTraceStepRecord,
    TargetChannelType,
)
from .session_lifecycle_log_archiver_types import SessionExecutionTurn


class CrossPlatformChannelHandoffCoordinator:
    """Coordinates seamless session handoff across heterogeneous chat platforms."""

    def __init__(self, signing_secret: str = "myrm-channel-handoff-secret") -> None:
        """Initialize handoff coordinator with HMAC signing secret."""
        self._secret = signing_secret

    def create_thread_anchor(
        self,
        session_id: str,
        target_channel: TargetChannelType,
    ) -> ChannelThreadAnchorDescriptor:
        """Construct platform-native thread anchor descriptor."""
        clean_id = session_id.replace("-", "")[:8]

        if target_channel == TargetChannelType.TELEGRAM:
            return ChannelThreadAnchorDescriptor(
                channel_type=target_channel,
                thread_kind=ChannelThreadKind.FORUM_TOPIC,
                thread_identifier=f"topic_{clean_id}",
                platform_metadata={"topic_name": f"Myrm Session {clean_id}"},
            )
        if target_channel == TargetChannelType.DISCORD:
            return ChannelThreadAnchorDescriptor(
                channel_type=target_channel,
                thread_kind=ChannelThreadKind.AUTO_ARCHIVE_THREAD,
                thread_identifier=f"thread_{clean_id}",
                platform_metadata={"auto_archive_minutes": "1440"},
            )
        if target_channel == TargetChannelType.SLACK:
            return ChannelThreadAnchorDescriptor(
                channel_type=target_channel,
                thread_kind=ChannelThreadKind.ANCHOR_MESSAGE,
                thread_identifier=f"slack_thread_{clean_id}",
                parent_message_id=f"msg_anchor_{clean_id}",
                platform_metadata={"broadcast_reply": "false"},
            )
        if target_channel == TargetChannelType.FEISHU:
            return ChannelThreadAnchorDescriptor(
                channel_type=target_channel,
                thread_kind=ChannelThreadKind.TOPIC_CONTAINER,
                thread_identifier=f"feishu_topic_{clean_id}",
                platform_metadata={"root_message_id": f"om_{clean_id}"},
            )

        return ChannelThreadAnchorDescriptor(
            channel_type=target_channel,
            thread_kind=ChannelThreadKind.DIRECT_CHANNEL,
            thread_identifier=f"direct_{clean_id}",
        )

    def initiate_handoff(
        self,
        session_id: str,
        source_channel: TargetChannelType,
        target_channel: TargetChannelType,
        turns_count: int,
        state_fingerprint: str,
    ) -> HandoffSessionEnvelope:
        """Issue a cryptographically verifiable handoff envelope."""
        now_iso = datetime.now(UTC).isoformat()
        anchor = self.create_thread_anchor(session_id, target_channel)

        raw_token_data = (
            f"{session_id}:{source_channel.value}:{target_channel.value}:"
            f"{state_fingerprint}:{now_iso}:{self._secret}"
        )
        token = hashlib.sha256(raw_token_data.encode("utf-8")).hexdigest()

        return HandoffSessionEnvelope(
            session_id=session_id,
            source_channel=source_channel,
            target_channel=target_channel,
            thread_anchor=anchor,
            resumption_token=token,
            state_fingerprint=state_fingerprint,
            created_at=now_iso,
            context_turns_count=turns_count,
        )

    def verify_resumption_token(
        self,
        envelope: HandoffSessionEnvelope,
    ) -> bool:
        """Verify token authenticity and integrity of a handoff envelope."""
        expected_raw = (
            f"{envelope.session_id}:{envelope.source_channel.value}:"
            f"{envelope.target_channel.value}:{envelope.state_fingerprint}:"
            f"{envelope.created_at}:{self._secret}"
        )
        expected_token = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()
        return envelope.resumption_token == expected_token


class HuggingFaceAgentTraceExporter:
    """Exports session execution transcripts to HuggingFace Agent Trace Viewer format."""

    _REDACT_KEYS_RE = re.compile(
        r"(sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"
    )

    def export_trace_steps(
        self,
        turns: list[SessionExecutionTurn],
        redact: bool = True,
    ) -> list[HFTraceStepRecord]:
        """Convert turns into HF Trace step records."""
        steps: list[HFTraceStepRecord] = []
        step_idx = 1

        for turn in turns:
            user_msg = turn.user_input
            if redact:
                user_msg = self._REDACT_KEYS_RE.sub("[REDACTED_SECRET]", user_msg)

            # Step 1: User prompt step
            steps.append(
                HFTraceStepRecord(
                    step_number=step_idx,
                    role="user",
                    final_output=user_msg,
                    timestamp=turn.timestamp,
                )
            )
            step_idx += 1

            # Intermediate tool action steps
            for tool in turn.tool_calls:
                clean_args = dict(tool.arguments)
                clean_result = tool.result_payload
                if redact:
                    clean_args = {
                        k: self._REDACT_KEYS_RE.sub("[REDACTED_SECRET]", v)
                        for k, v in clean_args.items()
                    }
                    clean_result = self._REDACT_KEYS_RE.sub(
                        "[REDACTED_SECRET]", clean_result
                    )

                steps.append(
                    HFTraceStepRecord(
                        step_number=step_idx,
                        role="agent",
                        thought=f"Invoking {tool.tool_name}",
                        action_tool=tool.tool_name,
                        action_input=clean_args,
                        observation=clean_result,
                        duration_ms=tool.duration_ms,
                        timestamp=tool.timestamp,
                    )
                )
                step_idx += 1

            # Final assistant response step
            asst_msg = turn.assistant_response
            if redact:
                asst_msg = self._REDACT_KEYS_RE.sub("[REDACTED_SECRET]", asst_msg)

            steps.append(
                HFTraceStepRecord(
                    step_number=step_idx,
                    role="assistant",
                    final_output=asst_msg,
                    timestamp=turn.timestamp,
                )
            )
            step_idx += 1

        return steps

    def export_trace_jsonl(
        self,
        turns: list[SessionExecutionTurn],
        redact: bool = True,
    ) -> str:
        """Serialize session turns into HuggingFace Agent Trace compatible JSONL string."""
        steps = self.export_trace_steps(turns, redact=redact)
        lines: list[str] = []

        for s in steps:
            step_dict = {
                "step": s.step_number,
                "role": s.role,
                "thought": s.thought,
                "action": s.action_tool,
                "action_input": s.action_input,
                "observation": s.observation,
                "output": s.final_output,
                "duration_ms": s.duration_ms,
                "timestamp": s.timestamp,
            }
            lines.append(json.dumps(step_dict, ensure_ascii=False))

        return "\n".join(lines)
