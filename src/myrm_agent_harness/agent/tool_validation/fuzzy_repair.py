"""Fuzzy tool name auto-repair and tool-call ID uniquification engine.

Resolves model hallucinated typos, case discrepancies, and duplicate tool-call IDs
often emitted by open-weights models or proxy gateways without corrupting downstream
dispatch pipelines.

[OUTPUT]
- ToolNameFuzzyRepairer: Performs exact, canonical, alias, and fuzzy distance name repair.
- ToolCallIdUniquifier: Ensures all tool-call IDs in a batch are session-globally unique.

[INPUT]
- __future__
- difflib

[OUTPUT]
- ToolNameFuzzyRepairer
- ToolCallIdUniquifier

[POS]
Fuzzy tool name auto-repair and tool-call ID uniquification engine.
"""

from __future__ import annotations

import difflib

from myrm_agent_harness.agent.tool_validation.validation_types import ToolCallEnvelope


class ToolNameFuzzyRepairer:
    """Repairs common tool name hallucinations and typos within safe similarity thresholds."""

    def __init__(
        self,
        alias_map: dict[str, str] | None = None,
        similarity_threshold: float = 0.82,
    ) -> None:
        self.alias_map: dict[str, str] = dict(alias_map) if alias_map else {}
        self.similarity_threshold: float = max(0.5, min(1.0, similarity_threshold))

    @staticmethod
    def _normalize_identifier(name: str) -> str:
        """Strip punctuation and normalize casing to snake-case style for heuristic comparison."""
        return name.lower().replace("-", "_").replace(" ", "_").strip()

    def repair_name(self, raw_name: str, valid_names: set[str]) -> str | None:
        """Attempt to repair a raw tool name against the set of registered valid names.

        Returns:
            The canonical tool name if safely repairable; None if ambiguous or unknown.
        """
        # 1. Exact match
        if raw_name in valid_names:
            return raw_name

        # 2. Explicit alias dictionary
        if raw_name in self.alias_map:
            target = self.alias_map[raw_name]
            if target in valid_names:
                return target

        # 3. Normalized case-insensitive / separator matching
        raw_norm = self._normalize_identifier(raw_name)
        norm_to_valid = {self._normalize_identifier(v): v for v in valid_names}
        if raw_norm in norm_to_valid:
            return norm_to_valid[raw_norm]

        # 4. Fuzzy SequenceMatcher comparison
        best_candidate: str | None = None
        best_ratio: float = 0.0

        for valid in valid_names:
            valid_norm = self._normalize_identifier(valid)
            ratio = difflib.SequenceMatcher(None, raw_norm, valid_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_candidate = valid

        if best_ratio >= self.similarity_threshold and best_candidate is not None:
            return best_candidate

        return None


class ToolCallIdUniquifier:
    """Ensures tool-call IDs in an inbound LLM batch are strictly unique."""

    @staticmethod
    def uniquify(
        calls: list[ToolCallEnvelope] | tuple[ToolCallEnvelope, ...],
        taken_ids: set[str] | None = None,
    ) -> tuple[ToolCallEnvelope, ...]:
        """Deduplicate tool call IDs across the current batch and already-used session IDs."""
        known = set(taken_ids) if taken_ids else set()
        result: list[ToolCallEnvelope] = []

        for call in calls:
            orig_id = call.id if call.id.strip() else f"call_{call.index}"
            candidate_id = orig_id
            counter = 1

            while candidate_id in known:
                candidate_id = f"{orig_id}_dup{counter}"
                counter += 1

            known.add(candidate_id)

            if candidate_id != call.id:
                result.append(
                    ToolCallEnvelope(
                        id=candidate_id,
                        name=call.name,
                        arguments=call.arguments,
                        index=call.index,
                    )
                )
            else:
                result.append(call)

        return tuple(result)
