"""Universal Harness Session Handoff and Full-State Bridge Engine (Item 211).

[INPUT]
- session_bridge_types: Formats, traces, message models, and handoff bundles.

[OUTPUT]
- UniversalSessionBridgeEngine: Parser, state extractor, and bidirectional export converter.

[POS]
- Bridges external CLI/Web agent transcripts (Claude Code, OpenAI Codex, Web AI exports)
- into Myrm with lossless tool execution traces, CWD, git diffs, and round-trip export.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_exporter import (
    SessionBridgeExporter,
)
from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_types import (
    BridgeMessageItem,
    ExportBridgeResult,
    ExternalHarnessFormat,
    FullStateHandoffBundle,
    SessionWorkspaceState,
    ToolExecutionTrace,
    UniversalSessionDescriptor,
)


class UniversalSessionBridgeEngine:
    """Engine parsing external agent transcripts and executing bidirectional round-trip export."""

    def parse_claude_code_session(
        self,
        payload: str | list[dict[str, object]] | dict[str, object],
        source_path: str = "",
    ) -> FullStateHandoffBundle:
        """Parses Claude Code transcript, preserving tool calls, tool results, thinking, and CWD."""
        raw_data = self._coerce_json_object(payload)
        session_id = str(raw_data.get("session_id", raw_data.get("id", f"claude_{uuid.uuid4().hex[:8]}")))
        cwd = str(raw_data.get("cwd", raw_data.get("working_directory", "")))
        git_diff = str(raw_data.get("git_diff", raw_data.get("uncommitted_diff", "")))
        git_branch = str(raw_data.get("git_branch", ""))

        workspace_state = SessionWorkspaceState(
            cwd=cwd,
            uncommitted_git_diff=git_diff,
            git_branch=git_branch,
        )

        raw_messages = raw_data.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []

        messages: list[BridgeMessageItem] = []
        pending_tool_calls: dict[str, ToolExecutionTrace] = {}

        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            thinking = str(msg.get("thinking", ""))

            # Extract tool uses
            tool_traces: list[ToolExecutionTrace] = []
            raw_tool_uses = msg.get("tool_use", msg.get("tool_calls", []))
            if isinstance(raw_tool_uses, list):
                for tu in raw_tool_uses:
                    if isinstance(tu, dict):
                        call_id = str(tu.get("id", tu.get("tool_call_id", str(uuid.uuid4()))))
                        name = str(tu.get("name", tu.get("tool_name", "unknown_tool")))
                        args = tu.get("input", tu.get("arguments", {}))
                        arg_dict = args if isinstance(args, dict) else {}
                        trace = ToolExecutionTrace(
                            tool_name=name,
                            tool_call_id=call_id,
                            arguments=arg_dict,
                        )
                        pending_tool_calls[call_id] = trace
                        tool_traces.append(trace)

            # Match tool results
            raw_tool_results = msg.get("tool_results", [])
            if isinstance(raw_tool_results, list):
                for tr in raw_tool_results:
                    if isinstance(tr, dict):
                        cid = str(tr.get("tool_use_id", tr.get("tool_call_id", "")))
                        output_val = str(tr.get("content", tr.get("output", "")))
                        is_err = bool(tr.get("is_error", False))
                        matched_in_current = False
                        for idx, trace in enumerate(tool_traces):
                            if trace.tool_call_id == cid:
                                tool_traces[idx] = ToolExecutionTrace(
                                    tool_name=trace.tool_name,
                                    tool_call_id=trace.tool_call_id,
                                    arguments=trace.arguments,
                                    output=output_val,
                                    is_error=is_err,
                                )
                                pending_tool_calls[cid] = tool_traces[idx]
                                matched_in_current = True
                                break

                        if not matched_in_current and cid in pending_tool_calls:
                            prev = pending_tool_calls[cid]
                            updated_trace = ToolExecutionTrace(
                                tool_name=prev.tool_name,
                                tool_call_id=prev.tool_call_id,
                                arguments=prev.arguments,
                                output=output_val,
                                is_error=is_err,
                            )
                            pending_tool_calls[cid] = updated_trace
                            tool_traces.append(updated_trace)

            messages.append(
                BridgeMessageItem(
                    role=role,
                    content=content,
                    thinking=thinking,
                    tool_traces=tool_traces,
                )
            )

        title = str(raw_data.get("title", f"Claude Code Session {session_id[:8]}"))
        descriptor = UniversalSessionDescriptor(
            session_id=session_id,
            format=ExternalHarnessFormat.CLAUDE_CODE,
            title=title,
            turn_count=max(1, len(messages) // 2),
            message_count=len(messages),
            source_path=source_path,
        )

        return FullStateHandoffBundle(
            descriptor=descriptor,
            workspace_state=workspace_state,
            messages=messages,
            accumulated_tokens=int(raw_data.get("total_tokens", 0)),
            model_name=str(raw_data.get("model", "claude-3-5-sonnet")),
        )

    def parse_openai_codex_session(
        self,
        payload: str | list[dict[str, object]] | dict[str, object],
        source_path: str = "",
    ) -> FullStateHandoffBundle:
        """Parses OpenAI Codex rollout JSONL/JSON transcript, preserving tool calls and outputs."""
        items = self._coerce_json_lines(payload)
        session_id = f"codex_{uuid.uuid4().hex[:8]}"
        cwd = ""
        model_name = "codex-astra"
        messages: list[BridgeMessageItem] = []

        for line_item in items:
            if not isinstance(line_item, dict):
                continue

            event_type = str(line_item.get("type", line_item.get("event", "")))
            if event_type == "session_start" or "cwd" in line_item:
                cwd = str(line_item.get("cwd", cwd))
                sid = line_item.get("session_id")
                if sid:
                    session_id = str(sid)
                model_name = str(line_item.get("model", model_name))

            role = str(line_item.get("role", ""))
            content = str(line_item.get("content", line_item.get("message", "")))

            tool_traces: list[ToolExecutionTrace] = []
            raw_tools = line_item.get("tool_calls", line_item.get("function_calls", []))
            if isinstance(raw_tools, list):
                for tc in raw_tools:
                    if isinstance(tc, dict):
                        tname = str(tc.get("name", tc.get("function", {}).get("name", "tool")))
                        tcall_id = str(tc.get("id", str(uuid.uuid4())))
                        targs = tc.get("arguments", tc.get("function", {}).get("arguments", {}))
                        targ_dict = targs if isinstance(targs, dict) else {}
                        tout = str(tc.get("output", tc.get("result", "")))
                        tool_traces.append(
                            ToolExecutionTrace(
                                tool_name=tname,
                                tool_call_id=tcall_id,
                                arguments=targ_dict,
                                output=tout,
                            )
                        )

            if role or content or tool_traces:
                messages.append(
                    BridgeMessageItem(
                        role=role or "assistant",
                        content=content,
                        tool_traces=tool_traces,
                    )
                )

        workspace_state = SessionWorkspaceState(cwd=cwd)
        descriptor = UniversalSessionDescriptor(
            session_id=session_id,
            format=ExternalHarnessFormat.OPENAI_CODEX,
            title=f"Codex Rollout {session_id[:8]}",
            turn_count=max(1, len(messages) // 2),
            message_count=len(messages),
            source_path=source_path,
        )

        return FullStateHandoffBundle(
            descriptor=descriptor,
            workspace_state=workspace_state,
            messages=messages,
            model_name=model_name,
        )

    def parse_web_ai_chat_export(
        self,
        payload: str | dict[str, object],
        source_path: str = "",
    ) -> FullStateHandoffBundle:
        """Parses Web AI chat export JSON or Markdown, stripping boilerplate disclaimers."""
        messages: list[BridgeMessageItem] = []
        title = "Web AI Exported Session"
        session_id = f"web_{uuid.uuid4().hex[:8]}"

        if isinstance(payload, dict) or (isinstance(payload, str) and payload.strip().startswith("{")):
            raw_obj = self._coerce_json_object(payload)
            title = str(raw_obj.get("title", title))
            session_id = str(raw_obj.get("id", session_id))
            raw_msgs = raw_obj.get("messages", raw_obj.get("chat_messages", []))
            if isinstance(raw_msgs, list):
                for m in raw_msgs:
                    if isinstance(m, dict):
                        role = str(m.get("role", "user"))
                        content = self._sanitize_web_boilerplate(str(m.get("content", m.get("text", ""))))
                        if content.strip():
                            messages.append(BridgeMessageItem(role=role, content=content))
        else:
            # Parse Markdown format
            md_text = str(payload)
            lines = md_text.splitlines()
            current_role = "user"
            current_content: list[str] = []

            for line in lines:
                lower = line.strip().lower()
                if lower.startswith("### user") or lower.startswith("**user:**"):
                    if current_content:
                        clean_c = self._sanitize_web_boilerplate("\n".join(current_content))
                        if clean_c.strip():
                            messages.append(BridgeMessageItem(role=current_role, content=clean_c))
                        current_content = []
                    current_role = "user"
                elif lower.startswith("### assistant") or lower.startswith("**assistant:**"):
                    if current_content:
                        clean_c = self._sanitize_web_boilerplate("\n".join(current_content))
                        if clean_c.strip():
                            messages.append(BridgeMessageItem(role=current_role, content=clean_c))
                        current_content = []
                    current_role = "assistant"
                else:
                    current_content.append(line)

            if current_content:
                clean_c = self._sanitize_web_boilerplate("\n".join(current_content))
                if clean_c.strip():
                    messages.append(BridgeMessageItem(role=current_role, content=clean_c))

        descriptor = UniversalSessionDescriptor(
            session_id=session_id,
            format=ExternalHarnessFormat.WEB_CHAT_EXPORT,
            title=title,
            turn_count=max(1, len(messages) // 2),
            message_count=len(messages),
            source_path=source_path,
        )

        return FullStateHandoffBundle(
            descriptor=descriptor,
            workspace_state=SessionWorkspaceState(),
            messages=messages,
        )

    def export_to_claude_code(self, bundle: FullStateHandoffBundle) -> ExportBridgeResult:
        """Serializes handoff bundle back into Claude Code JSON structure."""
        return SessionBridgeExporter.export_to_claude_code(bundle)

    def export_to_openai_codex(self, bundle: FullStateHandoffBundle) -> ExportBridgeResult:
        """Serializes handoff bundle back into Codex rollout JSON Lines format."""
        return SessionBridgeExporter.export_to_openai_codex(bundle)

    def discover_and_index_sessions(
        self, raw_entries: list[tuple[ExternalHarnessFormat, str, str]]
    ) -> list[UniversalSessionDescriptor]:
        """Scans multiple external session files and extracts concise descriptors for UI selection."""
        descriptors: list[UniversalSessionDescriptor] = []
        for fmt, source_path, payload in raw_entries:
            try:
                if fmt == ExternalHarnessFormat.CLAUDE_CODE:
                    bundle = self.parse_claude_code_session(payload, source_path)
                elif fmt == ExternalHarnessFormat.OPENAI_CODEX:
                    bundle = self.parse_openai_codex_session(payload, source_path)
                else:
                    bundle = self.parse_web_ai_chat_export(payload, source_path)
                descriptors.append(bundle.descriptor)
            except Exception:
                continue
        return descriptors

    def _coerce_json_object(self, payload: str | list[dict[str, object]] | dict[str, object]) -> dict[str, object]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"messages": payload}
        if isinstance(payload, str):
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"messages": parsed}
        return {}

    def _coerce_json_lines(self, payload: str | list[dict[str, object]] | dict[str, object]) -> list[dict[str, object]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, str):
            lines = [l.strip() for l in payload.splitlines() if l.strip()]
            records: list[dict[str, object]] = []
            for line in lines:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        records.append(obj)
                except Exception:
                    continue
            return records
        return []

    def _sanitize_web_boilerplate(self, text: str) -> str:
        """Removes common web export disclaimer headers and wrapper artefacts."""
        cleaned = re.sub(r"(?i)^Disclaimer:.*?\n", "", text)
        cleaned = re.sub(r"(?i)^ChatGPT:\s*", "", cleaned)
        cleaned = re.sub(r"(?i)^Claude:\s*", "", cleaned)
        return cleaned.strip()
