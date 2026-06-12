"""HITL correction learning — converts approval edits/rejects into persistent memory.

Listens for APPROVAL_CORRECTION hook events and persists high-value signals as:
- SemanticMemory (preference_type="explicit") for argument value corrections
- ProceduralMemory (tool-scoped rules) for tool rejections or repeated patterns

Zero LLM cost: classification uses deterministic dict-diff and pattern matching.

[INPUT]
- core.hooks.types::HookResult, ApprovalCorrectionPayload, HookEvent
- toolkits.memory.types::SemanticMemory, ProceduralMemory, ToolRulePriority, RuleSource, PreferenceType

[OUTPUT]
- CorrectionLearningHook: Async hook handler for APPROVAL_CORRECTION events
- register_correction_learning: Convenience registration function

[POS]
Bridges the HITL approval flow with the memory system. Converts user
corrections (edits/rejects) into durable preferences and rules that
the agent automatically applies in future interactions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from myrm_agent_harness.core.hooks.types import HookResult
from myrm_agent_harness.toolkits.memory.types import (
    ProceduralMemory,
    RuleSource,
    SemanticMemory,
    ToolRulePriority,
)

logger = logging.getLogger(__name__)

# Path-related argument keys that indicate filesystem preference corrections
_PATH_ARG_KEYS = frozenset({"path", "file_path", "directory", "working_directory", "cwd", "target"})

# Command-related argument keys that indicate behavioral rule corrections
_COMMAND_ARG_KEYS = frozenset({"command", "cmd", "script", "code", "query"})


@dataclass(frozen=True, slots=True)
class CorrectionSignal:
    """A classified correction signal extracted from an approval decision."""

    tool_name: str
    decision_type: Literal["edit", "reject"]
    arg_key: str | None
    original_value: object
    corrected_value: object
    signal_class: Literal["path_preference", "command_rule", "arg_preference", "tool_rejection"]
    feedback: str


@dataclass
class _RepetitionTracker:
    """Tracks correction repetitions across the session for priority promotion."""

    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, fingerprint: str) -> int:
        self.counts[fingerprint] += 1
        return self.counts[fingerprint]


class CorrectionLearningHook:
    """Converts APPROVAL_CORRECTION events into persistent memory.

    Wired into the hook system via CallableHookDefinition. The handler:
    1. Extracts CorrectionSignals from the payload
    2. Deduplicates against recently created memories (session-level)
    3. Persists as SemanticMemory (preferences) or ProceduralMemory (rules)
    4. Returns learning summaries for frontend feedback

    Usage::

        hook = CorrectionLearningHook()
        registry.register(
            HookEvent.APPROVAL_CORRECTION,
            CallableHookDefinition(fn=hook.on_approval_correction),
        )
    """

    def __init__(self) -> None:
        self._repetition_tracker = _RepetitionTracker()
        self._recent_fingerprints: set[str] = set()
        self._pending_preferences: list[SemanticMemory] = []
        self._pending_rules: list[ProceduralMemory] = []

    @property
    def pending_preferences(self) -> list[SemanticMemory]:
        return list(self._pending_preferences)

    @property
    def pending_rules(self) -> list[ProceduralMemory]:
        return list(self._pending_rules)

    def drain_pending(self) -> tuple[list[SemanticMemory], list[ProceduralMemory]]:
        """Return and clear all pending memories for batch persistence."""
        prefs = self._pending_preferences
        rules = self._pending_rules
        self._pending_preferences = []
        self._pending_rules = []
        return prefs, rules

    async def on_approval_correction(self, event: str, payload: dict[str, object]) -> HookResult:
        """Handle APPROVAL_CORRECTION: extract, classify, and queue corrections."""
        corrections = payload.get("corrections")
        if not corrections or not isinstance(corrections, (list, tuple)):
            return HookResult(hook_type="correction_learning", success=True)

        signals = self._extract_signals(corrections)
        if not signals:
            return HookResult(hook_type="correction_learning", success=True)

        summaries: list[str] = []
        for signal in signals:
            fingerprint = f"{signal.tool_name}:{signal.arg_key}:{signal.signal_class}"

            if fingerprint in self._recent_fingerprints:
                continue
            self._recent_fingerprints.add(fingerprint)

            repetition_count = self._repetition_tracker.record(fingerprint)
            memory = self._create_memory(signal, repetition_count)
            if memory is None:
                continue

            if isinstance(memory, SemanticMemory):
                self._pending_preferences.append(memory)
                summaries.append(self._build_summary(signal, "preference"))
            else:
                self._pending_rules.append(memory)
                summaries.append(self._build_summary(signal, "rule"))

        await self._persist_pending()

        return HookResult(
            hook_type="correction_learning",
            success=True,
            output="; ".join(summaries) if summaries else None,
        )

    def _extract_signals(self, corrections: list | tuple) -> list[CorrectionSignal]:
        """Extract typed correction signals from raw correction dicts."""
        signals: list[CorrectionSignal] = []

        for correction in corrections:
            if not isinstance(correction, dict):
                continue

            tool_name = str(correction.get("tool_name", ""))
            decision_type = str(correction.get("decision_type", ""))
            if not tool_name or decision_type not in ("edit", "reject"):
                continue

            if decision_type == "reject":
                feedback = str(correction.get("feedback", "User rejected this tool call"))
                signals.append(
                    CorrectionSignal(
                        tool_name=tool_name,
                        decision_type="reject",
                        arg_key=None,
                        original_value=None,
                        corrected_value=None,
                        signal_class="tool_rejection",
                        feedback=feedback,
                    )
                )
                continue

            original_args = correction.get("original_args")
            edited_args = correction.get("edited_args")
            if not isinstance(original_args, dict) or not isinstance(edited_args, dict):
                continue

            for key in edited_args:
                original_val = original_args.get(key)
                edited_val = edited_args[key]
                if original_val == edited_val:
                    continue

                signal_class = self._classify_arg_change(key)
                feedback = str(correction.get("feedback", ""))
                signals.append(
                    CorrectionSignal(
                        tool_name=tool_name,
                        decision_type="edit",
                        arg_key=key,
                        original_value=original_val,
                        corrected_value=edited_val,
                        signal_class=signal_class,
                        feedback=feedback,
                    )
                )

        return signals

    def _classify_arg_change(self, arg_key: str) -> Literal["path_preference", "command_rule", "arg_preference"]:
        """Classify an argument change by its key name."""
        if arg_key in _PATH_ARG_KEYS:
            return "path_preference"
        if arg_key in _COMMAND_ARG_KEYS:
            return "command_rule"
        return "arg_preference"

    def _create_memory(
        self, signal: CorrectionSignal, repetition_count: int
    ) -> SemanticMemory | ProceduralMemory | None:
        """Create the appropriate memory type from a correction signal."""
        if signal.signal_class == "tool_rejection":
            return self._create_rejection_rule(signal, repetition_count)
        if signal.signal_class == "command_rule":
            return self._create_command_rule(signal, repetition_count)
        return self._create_preference(signal, repetition_count)

    def _create_preference(self, signal: CorrectionSignal, repetition_count: int) -> SemanticMemory:
        """Create a SemanticMemory preference from arg correction."""
        orig = _format_value(signal.original_value)
        corrected = _format_value(signal.corrected_value)

        if signal.signal_class == "path_preference":
            content = f"For {signal.tool_name}, prefer path: {corrected} (not {orig})"
        else:
            content = f"For {signal.tool_name}.{signal.arg_key}: prefer {corrected} over {orig}"

        strength = min(0.7 + repetition_count * 0.1, 1.0)

        return SemanticMemory(
            content=content,
            preference_type="explicit",
            preference_strength=strength,
            importance=0.8,
            tags=["hitl_correction", f"tool:{signal.tool_name}"],
        )

    def _create_command_rule(self, signal: CorrectionSignal, repetition_count: int) -> ProceduralMemory:
        """Create a ProceduralMemory rule from command correction."""
        orig = _format_value(signal.original_value)
        corrected = _format_value(signal.corrected_value)

        priority = ToolRulePriority.HIGH if repetition_count >= 2 else ToolRulePriority.NORMAL
        if repetition_count >= 3:
            priority = ToolRulePriority.CRITICAL

        return ProceduralMemory(
            content=f"When using {signal.tool_name}: use '{corrected}' instead of '{orig}'",
            trigger=f"Agent uses {signal.tool_name} with incorrect {signal.arg_key}",
            action=f"Replace with: {corrected}",
            tool_name=signal.tool_name,
            tool_rule_priority=priority,
            source=RuleSource.USER_EXPLICIT,
            language="en",
        )

    def _create_rejection_rule(self, signal: CorrectionSignal, repetition_count: int) -> ProceduralMemory:
        """Create a ProceduralMemory rule from tool rejection."""
        priority = ToolRulePriority.HIGH if repetition_count >= 2 else ToolRulePriority.NORMAL
        if repetition_count >= 3:
            priority = ToolRulePriority.CRITICAL

        feedback = signal.feedback or "User does not want this action"
        return ProceduralMemory(
            content=f"Avoid using {signal.tool_name} in this context: {feedback}",
            trigger=f"Agent attempts to use {signal.tool_name}",
            action=f"Consider alternative approach. User feedback: {feedback}",
            tool_name=signal.tool_name,
            tool_rule_priority=priority,
            source=RuleSource.USER_EXPLICIT,
            language="en",
        )

    def _build_summary(self, signal: CorrectionSignal, memory_type: str) -> str:
        """Build a human-readable learning summary for frontend feedback."""
        if signal.signal_class == "path_preference":
            return f"Remembered: will use {_format_value(signal.corrected_value)} for {signal.tool_name}"
        if signal.signal_class == "tool_rejection":
            return f"Remembered: avoid {signal.tool_name} in this context"
        if signal.signal_class == "command_rule":
            return f"Learned rule: use '{_format_value(signal.corrected_value)}' for {signal.tool_name}"
        return f"Learned {memory_type}: {signal.tool_name}.{signal.arg_key} preference updated"

    async def _persist_pending(self) -> None:
        """Persist pending memories via the current session's MemoryManager."""
        from myrm_agent_harness.agent._skill_agent_context import get_memory_manager

        manager = get_memory_manager()
        if manager is None:
            logger.debug("[CORRECTION_LEARNING] No memory manager available; memories queued only")
            return

        prefs, rules = self.drain_pending()

        for pref in prefs:
            try:
                await manager._store_semantic(pref)
                logger.info("[CORRECTION_LEARNING] Stored preference: %s", pref.content[:80])
            except Exception as e:
                logger.warning("[CORRECTION_LEARNING] Failed to store preference: %s", e)
                self._pending_preferences.append(pref)

        for rule in rules:
            try:
                await manager._store_procedural(rule)
                logger.info("[CORRECTION_LEARNING] Stored rule: %s", rule.content[:80])
            except Exception as e:
                logger.warning("[CORRECTION_LEARNING] Failed to store rule: %s", e)
                self._pending_rules.append(rule)


def _format_value(value: object) -> str:
    """Format a value for human-readable display, truncating if needed."""
    s = str(value) if value is not None else "<none>"
    return s[:120] + "..." if len(s) > 120 else s
