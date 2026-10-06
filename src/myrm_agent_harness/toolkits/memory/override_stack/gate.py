# [POS] src/myrm_agent_harness/toolkits/memory/override_stack/gate.py
# [INPUT] collections.abc.Sequence, typing, .types, .detector, myrm_agent_harness.toolkits.memory.types.ProceduralMemory
# [OUTPUT] EphemeralBypassGate, DynamicUserOverrideStack

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.override_stack.detector import (
    PlaybookConflictDetector,
)
from myrm_agent_harness.toolkits.memory.override_stack.types import (
    EphemeralBypassRecord,
    PlaybookOverrideEvaluation,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


class EphemeralBypassGate:
    """Evaluates turn prompt against procedural playbooks and temporarily bypasses conflicting rules."""

    def __init__(
        self, detector: PlaybookConflictDetector | None = None
    ) -> None:
        self._detector = detector or PlaybookConflictDetector()

    def evaluate(
        self,
        query: str,
        candidate_rules: Sequence[ProceduralMemory],
        session_decisions: Sequence[str] | None = None,
    ) -> PlaybookOverrideEvaluation:
        """Resolve priority conflicts and apply ephemeral zero-mutation bypasses."""
        active: list[ProceduralMemory] = []
        bypassed: list[EphemeralBypassRecord] = []

        for rule in candidate_rules:
            record = self._detector.detect_conflict(query=query, rule=rule)
            if record is not None:
                bypassed.append(record)
            else:
                active.append(rule)

        has_conflicts = len(bypassed) > 0
        injected_note = ""

        if has_conflicts:
            lines = [
                "【规约单次豁免注记 · Level 1 即时指令优先】",
                "以下长期沉淀规约已被用户当轮明确指令临时豁免，请遵照当轮要求执行，严禁拒绝或自作主张修改恢复：",
            ]
            for r in bypassed:
                lines.append(f"- 规约《{r.rule_id}》: {r.bypass_reason}")
            injected_note = "\n".join(lines)

        return PlaybookOverrideEvaluation(
            active_rules=tuple(active),
            bypassed_records=tuple(bypassed),
            injected_context_note=injected_note,
            has_conflicts=has_conflicts,
        )


class DynamicUserOverrideStack:
    """Orchestrates the immutable three-tier priority hierarchy: Turn Prompt > Session Decision > Procedural Playbook."""

    def __init__(self, gate: EphemeralBypassGate | None = None) -> None:
        self._gate = gate or EphemeralBypassGate()

    def resolve(
        self,
        turn_prompt: str,
        rules: Sequence[ProceduralMemory],
        session_decisions: Sequence[str] | None = None,
    ) -> PlaybookOverrideEvaluation:
        """Resolve override stack enforcing Level 1 prompt primacy over long-term rules."""
        return self._gate.evaluate(
            query=turn_prompt,
            candidate_rules=rules,
            session_decisions=session_decisions,
        )
