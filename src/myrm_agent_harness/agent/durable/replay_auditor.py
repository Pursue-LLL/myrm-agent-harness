"""Replay safety auditor and synthetic interrupted fallback synthesizer.

[INPUT]
- .types::IntentRecord, ReplayDecision, ReplaySafetyLevel, EffectType
- .protocols::ToolSafetyClassifierProtocol

[OUTPUT]
- DefaultToolSafetyClassifier: Introspects tool names and metadata to categorize safety level.
- ReplaySafetyAuditor: Evaluates pending uncompleted intents upon crash recovery.

[POS]
Decision engine preventing duplicate side-effects during crash recovery.
"""

from __future__ import annotations

from typing import Any

from myrm_agent_harness.agent.durable.protocols import ToolSafetyClassifierProtocol
from myrm_agent_harness.agent.durable.types import (
    EffectType,
    IntentRecord,
    ReplayDecision,
    ReplaySafetyLevel,
)

# Standard read-only safe tool whitelist
_SAFE_TOOL_PREFIXES = (
    "read_",
    "get_",
    "list_",
    "search_",
    "fetch_",
    "find_",
    "check_",
    "inspect_",
    "view_",
    "probe_",
)

_KNOWN_SAFE_TOOLS = {
    "web_search",
    "search_knowledge",
    "wiki_query",
    "read_file",
    "list_dir",
    "grep_code",
    "glob_files",
    "read_lints",
}


class DefaultToolSafetyClassifier(ToolSafetyClassifierProtocol):
    """Default safety classifier introspecting tool naming conventions and metadata."""

    def __init__(self, safe_tools: set[str] | None = None) -> None:
        self._safe_tools = set(safe_tools or set()).union(_KNOWN_SAFE_TOOLS)

    def classify_tool(self, tool_name: str, tool_args: dict[str, Any]) -> ReplayDecision:
        """Evaluate if the tool is safe to re-run or requires synthetic interruption."""
        name_lower = tool_name.lower().strip()
        if name_lower in self._safe_tools or any(name_lower.startswith(p) for p in _SAFE_TOOL_PREFIXES):
            return ReplayDecision(
                can_reexecute=True,
                safety_level=ReplaySafetyLevel.SAFE,
                reason=f"Tool '{tool_name}' is classified as read-only safe.",
            )

        # Non-idempotent or mutating tool: must NOT re-execute blindly
        synthetic_payload = {
            "status": "interrupted",
            "error_type": "ToolExecutionInterruptedError",
            "message": (
                f"Tool '{tool_name}' execution was interrupted by process termination or crash. "
                f"External side-effects may have partially applied. "
                f"Please inspect the current environment state before deciding whether to retry."
            ),
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
        return ReplayDecision(
            can_reexecute=False,
            safety_level=ReplaySafetyLevel.UNSAFE,
            synthetic_result_payload=synthetic_payload,
            reason=f"Tool '{tool_name}' produces mutating side-effects and cannot be automatically re-run.",
        )


class ReplaySafetyAuditor:
    """Audits uncompleted intents during recovery to decide re-run or synthetic fallback."""

    def __init__(self, classifier: ToolSafetyClassifierProtocol | None = None) -> None:
        self.classifier = classifier or DefaultToolSafetyClassifier()

    def audit_intent(self, intent: IntentRecord) -> ReplayDecision:
        """Audit an uncompleted intent."""
        if intent.effect_type == EffectType.MODEL_CALL:
            # Model calls are pure read/inference, safe to re-run
            return ReplayDecision(
                can_reexecute=True,
                safety_level=ReplaySafetyLevel.SAFE,
                reason="Model inference is idempotent and safe to re-request.",
            )

        if intent.effect_type == EffectType.CONTEXT_COMPACT:
            return ReplayDecision(
                can_reexecute=True,
                safety_level=ReplaySafetyLevel.SAFE,
                reason="Context compaction is deterministic and safe to re-execute.",
            )

        if intent.effect_type == EffectType.TOOL_EXECUTION:
            tool_name = intent.payload.get("tool_name", "unknown")
            tool_args = intent.payload.get("tool_args", {})
            return self.classifier.classify_tool(tool_name, tool_args)

        return ReplayDecision(
            can_reexecute=False,
            safety_level=ReplaySafetyLevel.UNSAFE,
            synthetic_result_payload={"status": "interrupted", "message": "Unknown effect type interrupted."},
            reason="Unrecognized effect type defaults to safe fallback.",
        )
