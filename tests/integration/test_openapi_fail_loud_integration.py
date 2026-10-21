"""Live integration: OpenAPI fail-loud uses real OpenAPIBridge fetch (no bridge mock)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.config.exceptions import ConfigIncompleteError
from myrm_agent_harness.agent.types import AgentRuntimeSpec


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_skill_agent_openapi_load_failed_live_bad_spec_url() -> None:
    """Real secure_fetch + OpenAPIBridge path must fail loud when spec URL is invalid."""
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    spec = AgentRuntimeSpec(
        agent_id="integration-openapi-load-fail",
        name="integration-openapi-load-fail",
        system_prompt="integration test",
        openapi_services=[
            {
                "name": "bad_svc",
                "enabled": True,
                "spec_url": "https://httpbin.org/status/404",
            }
        ],
    )

    with patch("myrm_agent_harness.agent.skill_agent.SkillAgent") as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        with pytest.raises(ConfigIncompleteError) as exc_info:
            await create_skill_agent(
                spec=spec,
                llm=MagicMock(),
                executor=MagicMock(),
            )

    assert exc_info.value.error_code == "openapi_load_failed"


_MINIMAL_OPENAPI_SPEC = """
openapi: 3.0.0
info:
  title: Integration Test API
  version: 1.0.0
servers:
  - url: https://example.com
paths:
  /items:
    get:
      operationId: listItems
      summary: List items
      responses:
        "200":
          description: ok
"""


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_skill_agent_openapi_succeeds_live_inline_spec() -> None:
    """Real OpenAPIBridge parse + tool generation from inline spec (no bridge mock)."""
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    spec = AgentRuntimeSpec(
        agent_id="integration-openapi-inline",
        name="integration-openapi-inline",
        system_prompt="integration test",
        openapi_services=[
            {
                "name": "items_api",
                "enabled": True,
                "spec_content": _MINIMAL_OPENAPI_SPEC,
                "selected_endpoints": ["listItems"],
            }
        ],
    )

    with patch("myrm_agent_harness.agent.skill_agent.SkillAgent") as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    call_kwargs = mock_skill_agent_cls.call_args.kwargs
    bound_tools = call_kwargs.get("tools") or []
    assert any("listItems" in getattr(tool, "name", "") for tool in bound_tools)
