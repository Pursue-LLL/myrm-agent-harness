"""Reverse export serialization bridge for external agent formats (Item 211).

[INPUT]
- session_bridge_types: Handoff bundles and export result models.

[OUTPUT]
- SessionBridgeExporter: Bidirectional serializer producing Claude Code and OpenAI Codex payloads.

[POS]
- Decouples reverse export serialization from ingestion parsing,
- enabling bidirectional round-trip interoperability with external harnesses.
"""

from __future__ import annotations

import json
import time

from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_types import (
    ExportBridgeResult,
    ExternalHarnessFormat,
    FullStateHandoffBundle,
)


class SessionBridgeExporter:
    """Serializes normalized Myrm session bundles back into foreign CLI and rollout formats."""

    @staticmethod
    def export_to_claude_code(bundle: FullStateHandoffBundle) -> ExportBridgeResult:
        """Serializes handoff bundle back into Claude Code JSON structure."""
        start_time = time.perf_counter()
        exported_messages: list[dict[str, object]] = []

        for msg in bundle.messages:
            msg_dict: dict[str, object] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.thinking:
                msg_dict["thinking"] = msg.thinking

            if msg.tool_traces:
                tool_uses: list[dict[str, object]] = []
                tool_results: list[dict[str, object]] = []
                for trace in msg.tool_traces:
                    tool_uses.append({
                        "id": trace.tool_call_id,
                        "name": trace.tool_name,
                        "input": trace.arguments,
                    })
                    if trace.output:
                        tool_results.append({
                            "tool_use_id": trace.tool_call_id,
                            "content": trace.output,
                            "is_error": trace.is_error,
                        })
                msg_dict["tool_use"] = tool_uses
                if tool_results:
                    msg_dict["tool_results"] = tool_results

            exported_messages.append(msg_dict)

        out_obj: dict[str, object] = {
            "session_id": bundle.descriptor.session_id,
            "title": bundle.descriptor.title,
            "cwd": bundle.workspace_state.cwd,
            "git_diff": bundle.workspace_state.uncommitted_git_diff,
            "git_branch": bundle.workspace_state.git_branch,
            "model": bundle.model_name or "claude-3-5-sonnet",
            "messages": exported_messages,
        }

        payload = json.dumps(out_obj, indent=2, ensure_ascii=False)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return ExportBridgeResult(
            target_format=ExternalHarnessFormat.CLAUDE_CODE,
            output_payload=payload,
            exported_message_count=len(exported_messages),
            export_duration_ms=round(duration_ms, 2),
        )

    @staticmethod
    def export_to_openai_codex(bundle: FullStateHandoffBundle) -> ExportBridgeResult:
        """Serializes handoff bundle back into Codex rollout JSON Lines format."""
        start_time = time.perf_counter()
        lines: list[str] = [
            json.dumps({
                "type": "session_start",
                "session_id": bundle.descriptor.session_id,
                "cwd": bundle.workspace_state.cwd,
                "model": bundle.model_name or "codex-astra",
            })
        ]

        for msg in bundle.messages:
            item: dict[str, object] = {
                "type": "message",
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_traces:
                item["tool_calls"] = [
                    {
                        "id": t.tool_call_id,
                        "name": t.tool_name,
                        "arguments": t.arguments,
                        "output": t.output,
                    }
                    for t in msg.tool_traces
                ]
            lines.append(json.dumps(item))

        payload = "\n".join(lines) + "\n"
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return ExportBridgeResult(
            target_format=ExternalHarnessFormat.OPENAI_CODEX,
            output_payload=payload,
            exported_message_count=len(bundle.messages),
            export_duration_ms=round(duration_ms, 2),
        )
