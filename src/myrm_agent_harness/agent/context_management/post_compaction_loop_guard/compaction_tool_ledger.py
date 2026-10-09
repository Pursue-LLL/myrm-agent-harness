# [INPUT]: BaseMessage, AIMessage, ToolMessage from langchain_core, ToolCallSignature, CompactionBoundaryLedger from tool_loop_types
# [OUTPUT]: CompactionToolLedgerExtractor, compute_arguments_hash, format_boundary_ledger_prompt
# [POS]: myrm_agent_harness.agent.context_management.post_compaction_loop_guard.compaction_tool_ledger
"""Compaction boundary tool execution ledger extractor and formatter (Item 331).

Captures recent tool call signatures, arguments hashes, and outcome digests at
the context compaction boundary, formatting them into persistent structured context.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Final
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.tool_loop_types import (
    DEFAULT_MAX_SIGNATURES,
    CompactionBoundaryLedger,
    ToolCallSignature,
)


def compute_arguments_hash(
    tool_name: str,
    arguments: dict[str, str | int | float | bool | list[str] | dict[str, str] | None] | str,
) -> tuple[str, str]:
    """Compute deterministic SHA-256 fingerprint from tool arguments.

    Args:
        tool_name: Tool identifier.
        arguments: Raw dictionary or JSON string of tool parameters.

    Returns:
        tuple of (arguments_hash, canonical_json_string)
    """
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            canonical_json = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        except Exception:
            canonical_json = arguments.strip()
    elif isinstance(arguments, dict):
        canonical_json = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    else:
        canonical_json = str(arguments)

    hasher = hashlib.sha256()
    hasher.update(tool_name.encode("utf-8"))
    hasher.update(b"::")
    hasher.update(canonical_json.encode("utf-8"))
    return hasher.hexdigest(), canonical_json


def format_boundary_ledger_prompt(ledger: CompactionBoundaryLedger) -> str:
    """Format boundary ledger into an immutable system prompt evidence block."""
    if not ledger.signatures:
        return ""

    lines: list[str] = [
        "=== COMPACTED TOOL EXECUTION LEDGER ===",
        "The following tool invocations were completed immediately prior to this context compaction boundary:",
    ]
    for idx, sig in enumerate(ledger.signatures, 1):
        lines.append(
            f"- [{idx}] Tool: '{sig.tool_name}' | Args: {sig.normalized_args_json} | Result Summary: '{sig.result_digest}'"
        )
    lines.append(
        "CRITICAL POLICY: The above results are authoritative and preserved. "
        "Do NOT redundantly re-invoke these exact tools unless explicitly directed."
    )
    lines.append("=========================================")
    return "\n".join(lines)


class CompactionToolLedgerExtractor:
    """Extractor capturing completed tool call receipts at compaction boundaries."""

    @classmethod
    def extract_ledger(
        cls,
        session_id: str,
        messages: list[BaseMessage],
        compaction_turn_index: int,
        max_signatures: int = DEFAULT_MAX_SIGNATURES,
    ) -> CompactionBoundaryLedger:
        """Scan message sequence and extract recent tool call receipts.

        Args:
            session_id: Session identifier.
            messages: Uncompressed message sequence prior to compaction.
            compaction_turn_index: Current turn counter.
            max_signatures: Maximum recent calls to retain.

        Returns:
            CompactionBoundaryLedger holding recent signatures.
        """
        # Map tool_call_id to ToolMessage content
        tool_results_by_id: dict[str, str] = {}
        for msg in messages:
            if isinstance(msg, ToolMessage) or getattr(msg, "type", "") == "tool":
                tc_id = getattr(msg, "tool_call_id", "")
                if tc_id:
                    content_str = str(msg.content)
                    # Keep concise digest
                    digest = content_str[:200].replace("\n", " ").strip()
                    if len(content_str) > 200:
                        digest += "..."
                    tool_results_by_id[tc_id] = digest

        # Collect tool calls from AIMessages in chronological order
        collected: list[ToolCallSignature] = []
        call_counter = 0

        for msg in messages:
            if isinstance(msg, AIMessage) or getattr(msg, "type", "") == "ai":
                raw_tool_calls = getattr(msg, "tool_calls", [])
                if not raw_tool_calls and "tool_calls" in getattr(msg, "additional_kwargs", {}):
                    raw_tool_calls = msg.additional_kwargs.get("tool_calls", [])

                for tc in raw_tool_calls:
                    call_counter += 1
                    t_name: str = ""
                    t_args: dict[str, str | int | float | bool | list[str] | dict[str, str] | None] | str = {}
                    t_id: str = ""

                    if isinstance(tc, dict):
                        t_id = tc.get("id", "")
                        if "function" in tc and isinstance(tc["function"], dict):
                            func_dict = tc["function"]
                            t_name = str(func_dict.get("name", ""))
                            t_args = func_dict.get("arguments", {})
                        else:
                            t_name = str(tc.get("name", ""))
                            t_args = tc.get("args", {})
                    else:
                        t_id = getattr(tc, "id", "")
                        t_name = getattr(tc, "name", "")
                        t_args = getattr(tc, "args", {})

                    if not t_name:
                        continue

                    args_hash, canonical_json = compute_arguments_hash(t_name, t_args)
                    res_digest = tool_results_by_id.get(t_id, "completed")

                    sig = ToolCallSignature(
                        tool_name=t_name,
                        arguments_hash=args_hash,
                        normalized_args_json=canonical_json,
                        result_digest=res_digest,
                        call_index=call_counter,
                        timestamp_iso=datetime.now(timezone.utc).isoformat(),
                    )
                    collected.append(sig)

        # Slice to the most recent N tool calls
        recent_signatures = collected[-max_signatures:] if max_signatures > 0 else collected

        # Compute tamper-evident hash of entire ledger
        hasher = hashlib.sha256()
        hasher.update(session_id.encode("utf-8"))
        hasher.update(str(compaction_turn_index).encode("utf-8"))
        for s in recent_signatures:
            hasher.update(s.arguments_hash.encode("utf-8"))
            hasher.update(s.result_digest.encode("utf-8"))

        return CompactionBoundaryLedger(
            session_id=session_id,
            compaction_turn_index=compaction_turn_index,
            signatures=recent_signatures,
            ledger_digest=hasher.hexdigest(),
        )
