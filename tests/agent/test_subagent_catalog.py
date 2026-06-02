import pytest

from myrm_agent_harness.agent.sub_agents.types import SubagentCatalog, SubagentConfig


class MockCatalog(SubagentCatalog):
    def __init__(self, configs: dict[str, SubagentConfig]):
        self._configs = configs

    async def resolve(self, type_id: str) -> SubagentConfig | None:
        return self._configs.get(type_id)


@pytest.mark.asyncio
async def test_subagent_catalog_protocol():
    config = SubagentConfig(system_prompt="Test", description="Test description")

    catalog = MockCatalog({"test_id": config})

    resolved = await catalog.resolve("test_id")
    assert resolved is not None
    assert resolved.system_prompt == "Test"

    not_found = await catalog.resolve("missing")
    assert not_found is None
