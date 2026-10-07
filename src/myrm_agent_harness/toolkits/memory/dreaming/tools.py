"""[POS]: src/myrm_agent_harness/toolkits/memory/dreaming/tools.py
[INPUT]: AutonomousDreamingSynthesizer and session fragments.
[OUTPUT]: DreamingMetaTools exposing agent meta-tools for autonomous dreaming and pruning.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamingSynthesisReport,
    DreamSessionFragment,
)
from myrm_agent_harness.toolkits.memory.dreaming.synthesizer import (
    AutonomousDreamingSynthesizer,
)


class DreamingMetaTools:
    """Agent-facing meta-tools to autonomously trigger dreaming consolidation and review pruned memories."""

    def __init__(self, synthesizer: AutonomousDreamingSynthesizer | None = None) -> None:
        self._synthesizer = synthesizer or AutonomousDreamingSynthesizer()

    def run_dreaming_consolidation(
        self,
        fragments_data: list[dict[str, object]],
        project_id: str | None = None,
    ) -> dict[str, object]:
        """Trigger an autonomous dreaming and pruning cycle over provided session fragments."""
        fragments: list[DreamSessionFragment] = []
        for d in fragments_data:
            session_id = str(d.get("session_id", "sess_unknown"))
            raw_memories = d.get("memories")
            memories = [m for m in raw_memories if isinstance(m, dict)] if isinstance(raw_memories, list) else []
            raw_keywords = d.get("topic_keywords")
            keywords = [str(k) for k in raw_keywords] if isinstance(raw_keywords, list) else []
            turns = int(d.get("chat_turn_count", 0))  # type: ignore[arg-type]
            proj = str(d.get("project_id")) if d.get("project_id") else project_id

            fragments.append(
                DreamSessionFragment(
                    session_id=session_id,
                    memories=memories,
                    topic_keywords=keywords,
                    chat_turn_count=turns,
                    project_id=proj,
                )
            )

        report: DreamingSynthesisReport = self._synthesizer.consolidate_and_prune(
            fragments=fragments,
            target_project_id=project_id,
        )
        return report.to_dict()
