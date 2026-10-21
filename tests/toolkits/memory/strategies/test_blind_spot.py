"""Unit tests for blind_spot knowledge extraction strategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.blind_spot import (
    BlindSpotCandidate,
    BlindSpotKnowledgePatch,
    BlindSpotResponse,
    PatchTargetType,
    extract_blind_spot_patches,
)


@pytest.mark.asyncio
async def test_extract_blind_spot_patches_empty_candidates_skips() -> None:
    report = await extract_blind_spot_patches([], None)
    assert report.skipped is True
    assert "Insufficient candidates" in report.skip_reason
    assert report.has_patches is False


@pytest.mark.asyncio
async def test_extract_blind_spot_patches_without_llm_skips() -> None:
    candidates = [
        BlindSpotCandidate(query="What is the internal bastion IP?", session_id="s1"),
    ]
    report = await extract_blind_spot_patches(candidates, None)
    assert report.skipped is True
    assert "No LLM provided" in report.skip_reason
    assert report.candidate_count == 1


@pytest.mark.asyncio
async def test_extract_blind_spot_patches_success() -> None:
    candidates = [
        BlindSpotCandidate(
            query="What is the staging bastion IP?",
            session_id="s1",
            user_correction="Bastion IP is 10.20.1.55 on port 2222",
            thumbs_down=True,
        ),
    ]

    mock_llm = MagicMock()
    mock_structured = AsyncMock()
    mock_llm.with_structured_output.return_value = mock_structured

    mock_response = BlindSpotResponse(
        patches=[
            BlindSpotKnowledgePatch(
                title="Staging Bastion IP",
                target_type=PatchTargetType.WIKI,
                content="Staging bastion is 10.20.1.55:2222 requiring private key",
                trigger_condition="Questions about staging bastion or jump server",
                rationale="User explicitly provided bastion IP after retrieval missed",
                confidence=0.95,
                source_queries=["What is the staging bastion IP?"],
                suggested_action="Save to infrastructure wiki",
            )
        ],
        summary_note="Identified staging infrastructure knowledge gap",
    )
    mock_structured.ainvoke.return_value = mock_response

    report = await extract_blind_spot_patches(candidates, mock_llm)
    assert report.skipped is False
    assert report.has_patches is True
    assert len(report.patches) == 1

    patch = report.patches[0]
    assert patch.title == "Staging Bastion IP"
    assert patch.target_type == PatchTargetType.WIKI
    assert patch.confidence == 0.95
    assert "10.20.1.55" in patch.content

    data = report.to_dict()
    assert isinstance(data["patches"], list)
    assert len(data["patches"]) == 1


@pytest.mark.asyncio
async def test_extract_blind_spot_patches_llm_exception_handled() -> None:
    candidates = [
        BlindSpotCandidate(query="How to configure feishu webhook?", session_id="s2"),
    ]

    mock_llm = MagicMock()
    mock_structured = AsyncMock()
    mock_llm.with_structured_output.return_value = mock_structured
    mock_structured.ainvoke.side_effect = RuntimeError("OpenAI API rate limit exceeded")

    report = await extract_blind_spot_patches(candidates, mock_llm)
    assert report.skipped is True
    assert "LLM extraction error" in report.skip_reason
    assert report.has_patches is False
