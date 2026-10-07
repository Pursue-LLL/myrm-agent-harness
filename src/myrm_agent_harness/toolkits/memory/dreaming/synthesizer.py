"""[POS]: src/myrm_agent_harness/toolkits/memory/dreaming/synthesizer.py
[INPUT]: GroundedDreamingEngine, MemoryPruningEngine, session fragments, and raw candidate memories.
[OUTPUT]: AutonomousDreamingSynthesizer coordinating cross-session synthesis and memory pruning.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.dreaming.engine import (
    GroundedDreamingEngine,
)
from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamingSynthesisReport,
    DreamSessionFragment,
)
from myrm_agent_harness.toolkits.memory.dreaming.pruner import (
    MemoryPruningEngine,
)


class AutonomousDreamingSynthesizer:
    """Coordinating engine for autonomous Dreaming & Pruning consolidation cycles."""

    def __init__(
        self,
        dreaming_engine: GroundedDreamingEngine | None = None,
        pruning_engine: MemoryPruningEngine | None = None,
    ) -> None:
        self._dreaming_engine = dreaming_engine or GroundedDreamingEngine()
        self._pruning_engine = pruning_engine or MemoryPruningEngine()

    def consolidate_and_prune(
        self,
        fragments: Sequence[DreamSessionFragment],
        raw_memories: list[dict[str, object]] | None = None,
        target_project_id: str | None = None,
    ) -> DreamingSynthesisReport:
        """Execute a full dreaming cycle: gather fragments -> synthesize insights -> prune obsolete items."""
        start_time = time.perf_counter()
        run_id = f"dream_run_{uuid.uuid4().hex[:8]}"

        # 1. Synthesize cross-session cognitive insights
        synthesized_entries = self._dreaming_engine.process_fragments(
            fragments=fragments,
            target_project_id=target_project_id,
        )

        # 2. Collect candidate memories for pruning screening
        candidates_to_prune: list[dict[str, object]] = []
        if raw_memories:
            candidates_to_prune.extend(raw_memories)

        # Also pull extracted memories from fragments into candidate pool
        for frag in fragments:
            for mem in frag.memories:
                candidates_to_prune.append(
                    {
                        "memory_id": str(mem.get("id") or mem.get("memory_id") or f"mem_{frag.session_id}_{uuid.uuid4().hex[:6]}"),
                        "content": str(mem.get("content", "")),
                        "confidence": float(mem.get("confidence", 0.5)),  # type: ignore[arg-type]
                    }
                )

        # 3. Prune redundant, conflicting, or decayed memories
        pruned_records = self._pruning_engine.evaluate_pruning(
            raw_memories=candidates_to_prune,
            synthesized_entries=synthesized_entries,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return DreamingSynthesisReport(
            run_id=run_id,
            timestamp=datetime.now(UTC),
            duration_ms=elapsed_ms,
            candidate_count=len(candidates_to_prune),
            synthesized_insights=synthesized_entries,
            pruned_records=pruned_records,
        )
