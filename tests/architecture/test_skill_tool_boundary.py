"""Architecture guard: discover_capability vs skill_market tool boundaries.

Prevents LLM schema regressions where paired tool descriptions lose cross-references
that disambiguate library search from external marketplace install.

Architecture Reference: src/myrm_agent_harness/agent/meta_tools/META_TOOLS_SYSTEM.md
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    create_discover_capability_tool,
)
from myrm_agent_harness.agent.meta_tools.skills.market.skill_market_tool import (
    create_skill_market_tool,
)

_DISCOVER_TOOL = "skill_search_tool"
_MARKETPLACE_TOOL = "skill_market_tool"


def _tool_description(tool: object) -> str:
    description = getattr(tool, "description", None)
    assert isinstance(description, str) and description.strip(), (
        f"Expected non-empty description on {getattr(tool, 'name', tool)!r}"
    )
    return description


@pytest.fixture
def discover_tool_market_off():
    return create_discover_capability_tool(skills=[], market_tool_mounted=False)


@pytest.fixture
def discover_tool_market_on():
    return create_discover_capability_tool(skills=[], market_tool_mounted=True)


@pytest.fixture
def marketplace_tool():
    backend = MagicMock()
    backend.install_from_url = MagicMock()
    backend.uninstall = MagicMock()
    return create_skill_market_tool(backend)


@pytest.mark.architecture
def test_discover_capability_description_when_market_mounted(
    discover_tool_market_on,
) -> None:
    description = _tool_description(discover_tool_market_on)
    assert _MARKETPLACE_TOOL in description
    assert "external markets" in description.lower() or "installing new skills" in description.lower()
    assert "bound to this agent" in description.lower() or "already available" in description.lower()


@pytest.mark.architecture
def test_discover_capability_description_when_market_off(
    discover_tool_market_off,
) -> None:
    description = _tool_description(discover_tool_market_off)
    assert _MARKETPLACE_TOOL not in description
    assert "Settings" in description or "设置" in description
    assert "bound to this agent" in description.lower() or "already available" in description.lower()


@pytest.mark.architecture
def test_skill_market_description_points_to_skill_search_tool(marketplace_tool) -> None:
    description = _tool_description(marketplace_tool)
    assert _DISCOVER_TOOL in description
    assert "already bound" in description.lower() or "bound to this agent" in description.lower()


@pytest.mark.architecture
def test_skill_tool_pair_mutual_cross_reference_when_market_mounted(discover_tool_market_on, marketplace_tool) -> None:
    discover_description = _tool_description(discover_tool_market_on)
    marketplace_description = _tool_description(marketplace_tool)
    assert _MARKETPLACE_TOOL in discover_description
    assert _DISCOVER_TOOL in marketplace_description
