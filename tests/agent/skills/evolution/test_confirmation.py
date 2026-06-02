from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.infra.confirmation import BatchEvolutionConfirmer


@pytest.fixture
def mock_llm():
    return AsyncMock()

@pytest.fixture
def candidates():
    return [
        {
            "skill_id": "skill1",
            "skill_name": "Test Skill",
            "skill_content_summary": "Test content",
            "proposed_type": "FIX",
            "proposed_direction": "Fix a bug",
            "recent_metrics": "Failed 3 times"
        },
        {
            "skill_id": "skill2",
            "skill_name": "Another Skill",
            "skill_content_summary": "More content",
            "proposed_type": "OPTIMIZE",
            "proposed_direction": "Make it faster",
        }
    ]

@pytest.mark.asyncio
async def test_batch_confirm_empty(mock_llm):
    confirmer = BatchEvolutionConfirmer(mock_llm)
    res = await confirmer.batch_confirm_evolution([], "test trigger")
    assert res == []

@pytest.mark.asyncio
async def test_batch_confirm_success(mock_llm, candidates):
    mock_llm.ainvoke.return_value = MagicMock(content='''
    ```json
    {
        "confirmations": [
            {
                "skill_id": "skill1",
                "confirmed": true,
                "reason": "Good idea",
                "confidence": 0.9
            },
            {
                "skill_id": "skill2",
                "confirmed": false,
                "reason": "Bad idea",
                "confidence": 0.8
            }
        ]
    }
    ```
    ''')

    confirmer = BatchEvolutionConfirmer(mock_llm)
    res = await confirmer.batch_confirm_evolution(candidates, "test context")

    assert len(res) == 2

    c1 = next(c for c in res if c.skill_id == "skill1")
    assert c1.confirmed is True
    assert c1.confidence == 0.9

    c2 = next(c for c in res if c.skill_id == "skill2")
    assert c2.confirmed is False
    assert c2.confidence == 0.8

@pytest.mark.asyncio
async def test_batch_confirm_missing_skill(mock_llm, candidates):
    # LLM returns missing skill
    mock_llm.ainvoke.return_value = MagicMock(content='''
    {
        "confirmations": [
            {
                "skill_id": "skill1",
                "confirmed": true,
                "reason": "Good idea",
                "confidence": 0.9
            }
        ]
    }
    ''')

    confirmer = BatchEvolutionConfirmer(mock_llm)
    res = await confirmer.batch_confirm_evolution(candidates, "test context")

    assert len(res) == 2
    c2 = next(c for c in res if c.skill_id == "skill2")
    assert c2.confirmed is False
    assert "did not return confirmation" in c2.reason

@pytest.mark.asyncio
async def test_batch_confirm_invalid_json(mock_llm, candidates):
    mock_llm.ainvoke.return_value = MagicMock(content='''not json''')

    confirmer = BatchEvolutionConfirmer(mock_llm)
    res = await confirmer.batch_confirm_evolution(candidates, "test context")

    assert len(res) == 2
    assert all(c.confirmed is False for c in res)
    assert all("Batch confirmation failed" in c.reason for c in res)

@pytest.mark.asyncio
async def test_batch_confirm_exception(mock_llm, candidates):
    mock_llm.ainvoke.side_effect = Exception("LLM Error")

    confirmer = BatchEvolutionConfirmer(mock_llm)
    res = await confirmer.batch_confirm_evolution(candidates, "test context")

    assert len(res) == 2
    assert all(c.confirmed is False for c in res)
    assert all("Batch confirmation failed" in c.reason for c in res)
