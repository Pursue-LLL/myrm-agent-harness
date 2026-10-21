"""fix_skill repairs a skill with the LLM variant pipeline.

A different skill whose text mentions the failing error (for example a
troubleshooting skill) must never be returned as the repair of the failing one.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.execution.evaluator import (
    SkillEvaluationRubric,
)

_ERROR = "AttributeError: 'DataFrame' object has no attribute 'append'"
_FIXED_BODY = "# excel-report\nBuild frames with pd.concat instead of DataFrame.append."
_OTHER_BODY = "# pandas-troubleshooting\nNotes on pandas errors, unrelated to excel reports."


def _record(skill_id: str, description: str, content: str) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=skill_id,
        description=description,
        content=content,
        path=f"skills/{skill_id}/SKILL.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, parent_id=None),
    )


def _llm() -> MagicMock:
    rubric = SkillEvaluationRubric(
        accuracy_score=0.9,
        anti_fragmentation_score=1.0,
        redundancy_score=1.0,
        is_general=True,
        reasoning="targeted fix",
    )

    async def ainvoke(messages: list[MagicMock], **kwargs: object) -> object:
        if "expert AI agent skill optimizer" in messages[0].content:
            return MagicMock(content=_FIXED_BODY)
        return rubric

    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=ainvoke)
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=ainvoke)
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SkillStore]:
    skill_store = SkillStore(db_path=tmp_path / "skills.db")
    yield skill_store
    skill_store.close()


@pytest.mark.asyncio
async def test_fix_uses_llm_variant_even_when_another_skill_mentions_the_error(store: SkillStore) -> None:
    await store.save_skill(
        _record("excel-report", "Build xlsx weekly reports", "# excel-report\nUse DataFrame.append.")
    )
    await store.save_skill(_record("pandas-troubleshooting", f"Known errors: {_ERROR}", _OTHER_BODY))
    llm = _llm()
    engine = SkillEvolutionEngine(store=store, llm=llm)

    proposal = await engine.fix_skill("excel-report", _ERROR)

    assert proposal is not None
    assert proposal.skill_id == "excel-report"
    assert proposal.evolution_type == EvolutionType.FIX
    assert proposal.proposed_content == _FIXED_BODY
    assert llm.ainvoke.await_count >= 1
