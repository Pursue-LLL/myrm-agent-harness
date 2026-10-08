"""Heterogeneous context hydration bridge for multi-harness bidirectional conversion.

[INPUT]
- SessionStateAST instances for export, or raw dictionaries/JSON payloads from
  external harnesses (Claude Code, Hermes, Codex, UHP Standard).

[OUTPUT]
- Target harness formatted dictionaries, or re-hydrated canonical SessionStateAST objects.

[POS]
- Harness context management in agent/context_management/cross_harness_ast/heterogeneous_hydration_bridge.py.
"""

from __future__ import annotations

import json
import time
from typing import Mapping, Sequence

from .ast_types import (
    AstArtifactRef,
    AstContentBlock,
    AstMessageRole,
    AstToolInvocation,
    AstTurn,
    HarnessTargetFormat,
    SessionStateAST,
)
from .state_ast_engine import SessionStateASTEngine


class HeterogeneousContextHydrationBridge:
    """Bilateral serializer and hydrator bridging alien harness formats and canonical AST."""

    @classmethod
    def serialize(
        cls,
        ast: SessionStateAST,
        target_format: HarnessTargetFormat,
    ) -> Mapping[str, object]:
        """Converts canonical SessionStateAST into the target harness's native payload."""
        if target_format == HarnessTargetFormat.CLAUDE_CODE:
            return cls._serialize_to_claude_code(ast)
        elif target_format == HarnessTargetFormat.HERMES:
            return cls._serialize_to_hermes(ast)
        elif target_format == HarnessTargetFormat.CODEX:
            return cls._serialize_to_codex(ast)
        elif target_format == HarnessTargetFormat.UHP_STANDARD:
            return cls._serialize_to_uhp_standard(ast)
        else:
            return cls._serialize_to_myrm_native(ast)

    @classmethod
    def hydrate(
        cls,
        payload: Mapping[str, object],
        source_format: HarnessTargetFormat,
    ) -> SessionStateAST:
        """Hydrates an alien harness payload back into a canonical SessionStateAST."""
        if source_format == HarnessTargetFormat.CLAUDE_CODE:
            return cls._hydrate_from_claude_code(payload)
        elif source_format == HarnessTargetFormat.HERMES:
            return cls._hydrate_from_hermes(payload)
        elif source_format == HarnessTargetFormat.CODEX:
            return cls._hydrate_from_codex(payload)
        elif source_format == HarnessTargetFormat.UHP_STANDARD:
            return cls._hydrate_from_uhp_standard(payload)
        else:
            return cls._hydrate_from_myrm_native(payload)

    # -------------------------------------------------------------------------
    # Target Serializers
    # -------------------------------------------------------------------------

    @classmethod
    def _serialize_to_claude_code(cls, ast: SessionStateAST) -> Mapping[str, object]:
        messages: list[dict[str, object]] = []
        for turn in ast.turns:
            role_str = "user" if turn.role == AstMessageRole.USER else "assistant"
            if turn.role == AstMessageRole.SYSTEM:
                role_str = "system"

            # Combine text content
            text_parts = [b.content for b in turn.content_blocks if b.block_type == "text"]
            combined_text = "\n".join(text_parts)

            msg_obj: dict[str, object] = {
                "role": role_str,
                "content": combined_text,
            }
            if turn.thinking_trace:
                msg_obj["thinking"] = turn.thinking_trace
            if turn.tool_invocations:
                tool_calls: list[dict[str, object]] = []
                for tool in turn.tool_invocations:
                    tool_calls.append({
                        "id": tool.tool_call_id,
                        "name": tool.tool_name,
                        "input": dict(tool.arguments),
                        "output": tool.result_output,
                    })
                msg_obj["tool_calls"] = tool_calls

            messages.append(msg_obj)

        return {
            "session_id": ast.session_id,
            "format": "claude_code",
            "messages": messages,
            "metadata": dict(ast.session_metadata),
        }

    @classmethod
    def _serialize_to_hermes(cls, ast: SessionStateAST) -> Mapping[str, object]:
        history: list[dict[str, object]] = []
        for turn in ast.turns:
            entry: dict[str, object] = {
                "turn_id": turn.turn_id,
                "role": turn.role.value,
                "content": "\n".join(b.content for b in turn.content_blocks if b.block_type == "text"),
                "timestamp": turn.timestamp_ms,
            }
            if turn.tool_invocations:
                entry["tool_executions"] = [
                    {
                        "call_id": t.tool_call_id,
                        "tool": t.tool_name,
                        "args": dict(t.arguments),
                        "result": t.result_output,
                        "error": t.is_error,
                    }
                    for t in turn.tool_invocations
                ]
            if turn.artifact_refs:
                entry["artifacts"] = [
                    {
                        "id": a.artifact_id,
                        "path": a.file_path,
                        "hash": a.sha256_digest,
                    }
                    for a in turn.artifact_refs
                ]
            history.append(entry)

        return {
            "session_id": ast.session_id,
            "agent_state": "active",
            "history": history,
        }

    @classmethod
    def _serialize_to_codex(cls, ast: SessionStateAST) -> Mapping[str, object]:
        messages: list[dict[str, object]] = []
        for turn in ast.turns:
            role = turn.role.value
            text = "\n".join(b.content for b in turn.content_blocks if b.block_type == "text")

            msg: dict[str, object] = {"role": role, "content": text}
            if turn.tool_invocations and role == "assistant":
                tool_calls: list[dict[str, object]] = []
                for t in turn.tool_invocations:
                    tool_calls.append({
                        "id": t.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": t.tool_name,
                            "arguments": json.dumps(dict(t.arguments)),
                        },
                    })
                msg["tool_calls"] = tool_calls
            messages.append(msg)

        return {
            "model": "codex",
            "session_id": ast.session_id,
            "messages": messages,
        }

    @classmethod
    def _serialize_to_uhp_standard(cls, ast: SessionStateAST) -> Mapping[str, object]:
        turns_data: list[dict[str, object]] = []
        for turn in ast.turns:
            turns_data.append({
                "id": turn.turn_id,
                "role": turn.role.value,
                "blocks": [{"type": b.block_type, "content": b.content} for b in turn.content_blocks],
                "thinking": turn.thinking_trace,
                "tools": [
                    {
                        "call_id": t.tool_call_id,
                        "name": t.tool_name,
                        "arguments": dict(t.arguments),
                        "output": t.result_output,
                        "error": t.is_error,
                    }
                    for t in turn.tool_invocations
                ],
                "artifacts": [
                    {
                        "id": a.artifact_id,
                        "path": a.file_path,
                        "mime": a.mime_type,
                        "sha256": a.sha256_digest,
                        "summary": a.summary,
                    }
                    for a in turn.artifact_refs
                ],
                "timestamp_ms": turn.timestamp_ms,
            })

        return {
            "uhp_version": "1.0",
            "session_id": ast.session_id,
            "created_at_ms": ast.created_at_ms,
            "turns": turns_data,
            "metadata": dict(ast.session_metadata),
        }

    @classmethod
    def _serialize_to_myrm_native(cls, ast: SessionStateAST) -> Mapping[str, object]:
        return cls._serialize_to_uhp_standard(ast)

    # -------------------------------------------------------------------------
    # Target Hydrators
    # -------------------------------------------------------------------------

    @classmethod
    def _hydrate_from_claude_code(cls, payload: Mapping[str, object]) -> SessionStateAST:
        session_id = str(payload.get("session_id") or f"claude-{int(time.time())}")
        messages = payload.get("messages")
        turns: list[AstTurn] = []

        if isinstance(messages, Sequence):
            for idx, msg in enumerate(messages):
                if not isinstance(msg, Mapping):
                    continue
                role_raw = str(msg.get("role") or "user").lower()
                role = AstMessageRole.USER
                if role_raw == "assistant":
                    role = AstMessageRole.ASSISTANT
                elif role_raw == "system":
                    role = AstMessageRole.SYSTEM

                content = str(msg.get("content") or "")
                thinking = str(msg.get("thinking") or "") or None

                tools_list: list[AstToolInvocation] = []
                raw_tools = msg.get("tool_calls")
                if isinstance(raw_tools, Sequence):
                    for t in raw_tools:
                        if isinstance(t, Mapping):
                            t_args = t.get("input")
                            clean_args = {str(k): str(v) for k, v in t_args.items()} if isinstance(t_args, Mapping) else {}
                            tools_list.append(
                                AstToolInvocation(
                                    tool_call_id=str(t.get("id") or f"call-{idx}"),
                                    tool_name=str(t.get("name") or "unknown_tool"),
                                    arguments=clean_args,
                                    result_output=str(t.get("output") or ""),
                                )
                            )

                turn = SessionStateASTEngine.build_turn(
                    turn_id=f"turn-{idx}",
                    role=role,
                    text_content=content,
                    thinking_trace=thinking,
                    tool_invocations=tuple(tools_list),
                )
                turns.append(turn)

        return SessionStateAST(
            session_id=session_id,
            created_at_ms=int(time.time() * 1000),
            turns=tuple(turns),
            session_metadata={"hydrated_from": "claude_code"},
        )

    @classmethod
    def _hydrate_from_hermes(cls, payload: Mapping[str, object]) -> SessionStateAST:
        session_id = str(payload.get("session_id") or f"hermes-{int(time.time())}")
        history = payload.get("history")
        turns: list[AstTurn] = []

        if isinstance(history, Sequence):
            for idx, entry in enumerate(history):
                if not isinstance(entry, Mapping):
                    continue
                turn_id = str(entry.get("turn_id") or f"turn-{idx}")
                role_raw = str(entry.get("role") or "user").lower()
                role = AstMessageRole.USER
                if role_raw == "assistant":
                    role = AstMessageRole.ASSISTANT
                elif role_raw == "system":
                    role = AstMessageRole.SYSTEM

                content = str(entry.get("content") or "")
                timestamp_ms = int(entry.get("timestamp") or time.time() * 1000)

                tools_list: list[AstToolInvocation] = []
                raw_tools = entry.get("tool_executions")
                if isinstance(raw_tools, Sequence):
                    for t in raw_tools:
                        if isinstance(t, Mapping):
                            raw_args = t.get("args")
                            clean_args = {str(k): str(v) for k, v in raw_args.items()} if isinstance(raw_args, Mapping) else {}
                            tools_list.append(
                                AstToolInvocation(
                                    tool_call_id=str(t.get("call_id") or f"call-{idx}"),
                                    tool_name=str(t.get("tool") or "unknown_tool"),
                                    arguments=clean_args,
                                    result_output=str(t.get("result") or ""),
                                    is_error=bool(t.get("error", False)),
                                )
                            )

                artifact_list: list[AstArtifactRef] = []
                raw_artifacts = entry.get("artifacts")
                if isinstance(raw_artifacts, Sequence):
                    for a in raw_artifacts:
                        if isinstance(a, Mapping):
                            artifact_list.append(
                                AstArtifactRef(
                                    artifact_id=str(a.get("id") or f"art-{idx}"),
                                    file_path=str(a.get("path") or ""),
                                    mime_type="application/octet-stream",
                                    sha256_digest=str(a.get("hash") or ""),
                                    summary="Restored from Hermes",
                                    created_turn_id=turn_id,
                                )
                            )

                turn = SessionStateASTEngine.build_turn(
                    turn_id=turn_id,
                    role=role,
                    text_content=content,
                    tool_invocations=tuple(tools_list),
                    artifact_refs=tuple(artifact_list),
                    timestamp_ms=timestamp_ms,
                )
                turns.append(turn)

        return SessionStateAST(
            session_id=session_id,
            created_at_ms=int(time.time() * 1000),
            turns=tuple(turns),
            session_metadata={"hydrated_from": "hermes"},
        )

    @classmethod
    def _hydrate_from_codex(cls, payload: Mapping[str, object]) -> SessionStateAST:
        session_id = str(payload.get("session_id") or f"codex-{int(time.time())}")
        messages = payload.get("messages")
        turns: list[AstTurn] = []

        if isinstance(messages, Sequence):
            for idx, msg in enumerate(messages):
                if not isinstance(msg, Mapping):
                    continue
                role_raw = str(msg.get("role") or "user").lower()
                role = AstMessageRole.USER
                if role_raw == "assistant":
                    role = AstMessageRole.ASSISTANT
                elif role_raw == "system":
                    role = AstMessageRole.SYSTEM

                content = str(msg.get("content") or "")
                tools_list: list[AstToolInvocation] = []
                raw_tools = msg.get("tool_calls")
                if isinstance(raw_tools, Sequence):
                    for t in raw_tools:
                        if isinstance(t, Mapping):
                            func_obj = t.get("function")
                            t_name = "unknown_tool"
                            t_args: dict[str, str] = {}
                            if isinstance(func_obj, Mapping):
                                t_name = str(func_obj.get("name") or "unknown_tool")
                                args_str = str(func_obj.get("arguments") or "{}")
                                try:
                                    parsed = json.loads(args_str)
                                    if isinstance(parsed, Mapping):
                                        t_args = {str(k): str(v) for k, v in parsed.items()}
                                except Exception:
                                    t_args = {"raw_args": args_str}

                            tools_list.append(
                                AstToolInvocation(
                                    tool_call_id=str(t.get("id") or f"call-{idx}"),
                                    tool_name=t_name,
                                    arguments=t_args,
                                    result_output="",
                                )
                            )

                turn = SessionStateASTEngine.build_turn(
                    turn_id=f"turn-{idx}",
                    role=role,
                    text_content=content,
                    tool_invocations=tuple(tools_list),
                )
                turns.append(turn)

        return SessionStateAST(
            session_id=session_id,
            created_at_ms=int(time.time() * 1000),
            turns=tuple(turns),
            session_metadata={"hydrated_from": "codex"},
        )

    @classmethod
    def _hydrate_from_uhp_standard(cls, payload: Mapping[str, object]) -> SessionStateAST:
        session_id = str(payload.get("session_id") or f"uhp-{int(time.time())}")
        created_at = int(payload.get("created_at_ms") or time.time() * 1000)
        turns_data = payload.get("turns")
        turns: list[AstTurn] = []

        if isinstance(turns_data, Sequence):
            for t in turns_data:
                if not isinstance(t, Mapping):
                    continue
                turn_id = str(t.get("id") or "turn")
                role_val = str(t.get("role") or "user")
                try:
                    role = AstMessageRole(role_val)
                except ValueError:
                    role = AstMessageRole.USER

                blocks: list[AstContentBlock] = []
                raw_blocks = t.get("blocks")
                if isinstance(raw_blocks, Sequence):
                    for b in raw_blocks:
                        if isinstance(b, Mapping):
                            blocks.append(
                                AstContentBlock(
                                    block_type=str(b.get("type") or "text"),
                                    content=str(b.get("content") or ""),
                                )
                            )

                tools_list: list[AstToolInvocation] = []
                raw_tools = t.get("tools")
                if isinstance(raw_tools, Sequence):
                    for tc in raw_tools:
                        if isinstance(tc, Mapping):
                            raw_args = tc.get("arguments")
                            args_dict = {str(k): str(v) for k, v in raw_args.items()} if isinstance(raw_args, Mapping) else {}
                            tools_list.append(
                                AstToolInvocation(
                                    tool_call_id=str(tc.get("call_id") or ""),
                                    tool_name=str(tc.get("name") or ""),
                                    arguments=args_dict,
                                    result_output=str(tc.get("output") or ""),
                                    is_error=bool(tc.get("error", False)),
                                )
                            )

                artifact_list: list[AstArtifactRef] = []
                raw_artifacts = t.get("artifacts")
                if isinstance(raw_artifacts, Sequence):
                    for a in raw_artifacts:
                        if isinstance(a, Mapping):
                            artifact_list.append(
                                AstArtifactRef(
                                    artifact_id=str(a.get("id") or ""),
                                    file_path=str(a.get("path") or ""),
                                    mime_type=str(a.get("mime") or "application/octet-stream"),
                                    sha256_digest=str(a.get("sha256") or ""),
                                    summary=str(a.get("summary") or ""),
                                    created_turn_id=turn_id,
                                )
                            )

                turns.append(
                    AstTurn(
                        turn_id=turn_id,
                        role=role,
                        content_blocks=tuple(blocks),
                        thinking_trace=str(t.get("thinking") or "") or None,
                        tool_invocations=tuple(tools_list),
                        artifact_refs=tuple(artifact_list),
                        timestamp_ms=int(t.get("timestamp_ms") or 0),
                    )
                )

        metadata_dict = {str(k): str(v) for k, v in payload.get("metadata", {}).items()} if isinstance(payload.get("metadata"), Mapping) else {}
        return SessionStateAST(
            session_id=session_id,
            created_at_ms=created_at,
            turns=tuple(turns),
            session_metadata=metadata_dict,
        )

    @classmethod
    def _hydrate_from_myrm_native(cls, payload: Mapping[str, object]) -> SessionStateAST:
        return cls._hydrate_from_uhp_standard(payload)
