from dataclasses import dataclass

import pytest

from myrm_agent_harness.toolkits.memory.cognitive.consolidator import CognitiveConsolidator
from myrm_agent_harness.toolkits.memory.health import MaintenanceReport


@dataclass
class _FakeMemoryManager:
    force_calls: list[bool]

    async def run_maintenance_cycle(self, *, force: bool = False) -> MaintenanceReport:
        self.force_calls.append(force)
        return MaintenanceReport(
            consolidation_merged=2,
            consolidation_corrected=1,
            consolidation_updated=3,
            forgotten_count=4,
            archived_count=5,
            duration_ms=12.5,
            insights=("merged stale duplicates"),
        )


@pytest.mark.asyncio
async def test_cognitive_consolidator_delegates_to_maintenance_cycle() -> None:
    manager = _FakeMemoryManager(force_calls=[])
    consolidator = CognitiveConsolidator(memory_manager=manager)

    result = await consolidator.run_consolidation()

    assert manager.force_calls == [True]
    assert result.memories_merged == 2
    assert result.corrected == 1
    assert result.updated == 3
    assert result.noise_removed == 4
    assert result.archived == 5
    assert result.insights == ("merged stale duplicates")
