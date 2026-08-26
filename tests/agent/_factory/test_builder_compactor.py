"""Unit tests for builder dedicated compactor wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent._factory.builder import create_skill_agent
from myrm_agent_harness.agent.types import AgentRuntimeSpec


@pytest.mark.asyncio
async def test_create_skill_agent_wires_compactor_aux_llm() -> None:
    primary_llm = MagicMock(spec=BaseChatModel)
    aux_fallback_llm = MagicMock(spec=BaseChatModel)
    executor = AsyncMock()

    spec = AgentRuntimeSpec(
        agent_id="test_agent",
        name="Test Agent",
        system_prompt="Test system prompt",
    )

    with patch(
        "myrm_agent_harness.agent.middlewares.create_context_pipeline_middleware"
    ) as mock_create_middleware:
        mock_create_middleware.return_value = MagicMock()

        await create_skill_agent(
            llm=primary_llm,
            spec=spec,
            executor=executor,
            fallback_llm=aux_fallback_llm,
        )

        mock_create_middleware.assert_called_once()
        _, kwargs = mock_create_middleware.call_args
        assert kwargs.get("llm") is primary_llm
        assert kwargs.get("summarizer_llm") is aux_fallback_llm
