"""[POS]: src/myrm_agent_harness/toolkits/memory/dreaming/pruner.py
[INPUT]: Candidate memories, synthesized dream entries, and contradiction policies.
[OUTPUT]: MemoryPruningEngine detecting redundant, decayed, and contradictory memory records.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamDiaryEntry,
    PrunedMemoryRecord,
    PruningDecisionKind,
)

_CONTRADICTION_PAIRS = [
    (r"\breact\b", r"\bsvelte\b"),
    (r"\bvue\b", r"\breact\b"),
    (r"\bjavascript\b", r"\btypescript\b"),
    (r"\blight mode\b", r"\bdark mode\b"),
    (r"\btabs\b", r"\bspaces\b"),
    (r"\b2 spaces\b", r"\b4 spaces\b"),
    (r"使用\s*react", r"迁移至\s*svelte|全面采用\s*svelte"),
    (r"浅色模式|亮色", r"深色模式|暗黑模式"),
]

_TOKEN_REGEX = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class MemoryPruningEngine:
    """Detects and prunes conflicting, redundant, or decayed memories during dreaming consolidation."""

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        return {tok.lower() for tok in _TOKEN_REGEX.findall(text) if len(tok) > 1}

    @classmethod
    def detect_contradiction(cls, text_a: str, text_b: str) -> bool:
        """Check whether two statements express conflicting facts or superseded preferences."""
        low_a = text_a.lower()
        low_b = text_b.lower()

        for pat_a, pat_b in _CONTRADICTION_PAIRS:
            if (re.search(pat_a, low_a) and re.search(pat_b, low_b)) or (
                re.search(pat_b, low_a) and re.search(pat_a, low_b)
            ):
                return True
        return False

    def evaluate_pruning(
        self,
        raw_memories: list[dict[str, object]],
        synthesized_entries: list[DreamDiaryEntry],
    ) -> list[PrunedMemoryRecord]:
        """Screen raw memories against synthesized higher-order insights to prune redundant or obsolete facts."""
        pruned_records: list[PrunedMemoryRecord] = []

        # 1. Map synthesized insights by tokens for overlap testing
        entry_tok_map = [
            (entry, self._tokenize(entry.cognitive_statement))
            for entry in synthesized_entries
        ]

        for mem in raw_memories:
            mem_id = str(mem.get("id") or mem.get("memory_id") or "")
            content = str(mem.get("content", "")).strip()
            confidence = float(mem.get("confidence", 0.5))  # type: ignore[arg-type]
            if not mem_id or not content:
                continue

            mem_tokens = self._tokenize(content)

            # A. Contradiction superseding check
            superseded = False
            for entry, _ in entry_tok_map:
                if self.detect_contradiction(content, entry.cognitive_statement):
                    pruned_records.append(
                        PrunedMemoryRecord(
                            memory_id=mem_id,
                            decision=PruningDecisionKind.CONTRADICTION_SUPERSEDED,
                            reason=f"Directly contradicted by newer synthesized insight: '{entry.cognitive_statement}'",
                            superseded_by_statement=entry.cognitive_statement,
                        )
                    )
                    superseded = True
                    break

            if superseded:
                continue

            # B. Redundant absorbed check (contained in synthesized higher-order insight)
            absorbed = False
            for entry, entry_tokens in entry_tok_map:
                if mem_tokens and mem_tokens.issubset(entry_tokens):
                    pruned_records.append(
                        PrunedMemoryRecord(
                            memory_id=mem_id,
                            decision=PruningDecisionKind.REDUNDANT_ABSORBED,
                            reason=f"Subsumed into synthesized higher-order insight '{entry.cognitive_statement}'",
                            superseded_by_statement=entry.cognitive_statement,
                        )
                    )
                    absorbed = True
                    break

            if absorbed:
                continue

            # C. Low confidence decay check
            if confidence < 0.25:
                pruned_records.append(
                    PrunedMemoryRecord(
                        memory_id=mem_id,
                        decision=PruningDecisionKind.STALE_DECAYED,
                        reason=f"Confidence {confidence:.2f} decayed below retention threshold (0.25)",
                    )
                )

        return pruned_records
