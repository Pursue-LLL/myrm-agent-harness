"""Protocol validation, compact anchor synthesis, and multi-intent decomposition engine.

[INPUT]
- toolkits.memory.procedure_experience.models::ProcedureMemoryEntry (POS: Types and models for procedure
  experience.)

[OUTPUT]
- ProcedureProtocolEngine: Protocol validation, compact anchor synthesis, and multi-intent decomposition
  engine.

[POS]
Protocol validation, compact anchor synthesis, and multi-intent decomposition engine.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/procedure_experience/procedure_protocol.py
# [INPUT]: src.myrm_agent_harness.toolkits.memory.procedure_experience.models
# [OUTPUT]: ProcedureProtocolEngine

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.procedure_experience.models import (
    ProcedureMemoryEntry,
)


class ProcedureProtocolEngine:
    """Protocol validation, compact anchor synthesis, and multi-intent decomposition engine."""

    def validate_protocol(self, entry: ProcedureMemoryEntry) -> list[str]:
        """Validate strict conformance to the 8-field procedure-shaped memory protocol."""
        violations: list[str] = []

        if not entry.operation_intent.strip():
            violations.append("Field 'operation_intent' must be a non-empty descriptive intent.")

        if not entry.preconditions:
            violations.append("Field 'preconditions' must specify at least one required condition.")

        if not entry.immutable_boundary:
            violations.append("Field 'immutable_boundary' must declare protected assets or boundaries.")

        if not entry.procedure_steps:
            violations.append("Field 'procedure_steps' must list sequential atomic executable actions.")

        if not entry.write_field_provenance:
            violations.append("Field 'write_field_provenance' must map output fields to their calculation origins.")

        if not entry.anti_patterns:
            violations.append("Field 'anti_patterns' must warn against known failure modes or pitfalls.")

        if not entry.applicability:
            violations.append("Field 'applicability' must detail positive matching contexts.")

        if not entry.negative_applicability:
            violations.append("Field 'negative_applicability' must explicitly exclude invalid scenarios.")

        return violations

    def generate_retrieval_anchor(
        self,
        operation_intent: str,
        preconditions: list[str],
        applicability: list[str],
    ) -> str:
        """Synthesize a compact retrieval anchor surface (e.g. name + retrieval_anchor)."""
        clean_intent = re.sub(r"[^\w\s-]", "", operation_intent.lower()).strip()
        tokens = [t for t in clean_intent.split() if len(t) > 2][:4]
        intent_slug = "-".join(tokens) if tokens else "intent"

        pre_slug = ",".join(p.split(":")[0].strip().lower() for p in preconditions[:3])
        app_slug = ",".join(a.split(":")[0].strip().lower() for a in applicability[:3])

        return f"intent:{intent_slug}|pre:{pre_slug}|app:{app_slug}"

    def split_multi_intent_raw_steps(self, raw_text: str) -> list[dict[str, str]]:
        """Decompose raw multi-intent trajectory into distinct single-intent fragments (Split over merge)."""
        fragments: list[dict[str, str]] = []
        pattern = re.compile(r"(?:###\s*Intent\s*[:：]|\bIntent\s*\d+\s*[:：])\s*(?P<intent>[^\n]+)", re.IGNORECASE)

        matches = list(pattern.finditer(raw_text))
        if not matches:
            # Fallback single intent
            return [{"intent": "default_operation", "body": raw_text.strip()}]

        for i, match in enumerate(matches):
            intent_title = match.group("intent").strip()
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
            body = raw_text[start_pos:end_pos].strip()

            fragments.append({"intent": intent_title, "body": body})

        return fragments
