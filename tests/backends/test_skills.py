"""Unit tests for skills system."""

import pytest

from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from tests.mocks import InMemorySkillBackend


class TestSkillMetadata:
    """Tests for SkillMetadata data class."""

    def test_regular_skill_metadata(self):
        """Test regular skill metadata."""
        skill = SkillMetadata(
            name="test_skill",
            description="A test skill",
            storage_skill_id="skill_123",
            storage_path="/skills/test_skill",
        )

        assert skill.name == "test_skill"
        assert skill.description == "A test skill"
        assert skill.storage_skill_id == "skill_123"
        assert skill.is_storage_skill
        assert not skill.is_mcp_skill

    def test_mcp_skill_metadata(self):
        """Test MCP skill metadata."""
        mcp_data = MCPSkillData(
            server="test-server",
            tools=["tool1", "tool2"],
            config=[{"key": "value"}],
        )

        skill = SkillMetadata(
            name="mcp_test_skill",
            description="An MCP skill",
            mcp=mcp_data,
        )

        assert skill.name == "mcp_test_skill"
        assert skill.is_mcp_skill
        assert not skill.is_storage_skill
        assert skill.mcp is not None
        assert skill.mcp.server == "test-server"
        assert len(skill.mcp.tools) == 2


class TestInMemorySkillBackend:
    """Tests for InMemorySkillBackend."""

    @pytest.fixture
    def backend(self):
        """Create a clean backend for each test."""
        backend = InMemorySkillBackend()
        yield backend
        backend.clear()

    @pytest.mark.asyncio
    async def test_add_and_load_skill(self, backend: InMemorySkillBackend):
        """Test adding and loading a skill."""
        skill = SkillMetadata(
            name="test_skill",
            description="A test skill",
            storage_skill_id="skill_123",
        )
        backend.add_skill(skill)

        # Load skill
        loaded = await backend.load_skills(["test_skill"])

        assert len(loaded) == 1
        assert loaded[0].name == "test_skill"
        assert loaded[0].description == "A test skill"

    @pytest.mark.asyncio
    async def test_load_nonexistent_skill_raises_error(self, backend: InMemorySkillBackend):
        """Test that loading nonexistent skill raises error."""
        with pytest.raises(ValueError, match="Skill not found"):
            await backend.load_skills(["nonexistent_skill"])

    @pytest.mark.asyncio
    async def test_get_skill_content(self, backend: InMemorySkillBackend):
        """Test getting skill content."""
        skill = SkillMetadata(name="test_skill", description="A test skill")
        content = "# Test Skill\n\nThis is a test skill."
        backend.add_skill(skill, content=content)

        # Get content
        loaded_content = await backend.get_skill_content("test_skill")

        assert loaded_content == content

    @pytest.mark.asyncio
    async def test_get_skill_content_default(self, backend: InMemorySkillBackend):
        """Test getting skill content with default generation."""
        skill = SkillMetadata(name="test_skill", description="A test skill")
        backend.add_skill(skill)  # No content provided

        # Get content (should be auto-generated)
        content = await backend.get_skill_content("test_skill")

        assert "test_skill" in content
        assert "A test skill" in content

    @pytest.mark.asyncio
    async def test_get_skill_resources(self, backend: InMemorySkillBackend):
        """Test getting skill resources."""
        skill = SkillMetadata(name="test_skill", description="A test skill")
        resources = {
            "script.py": b"print('hello')",
            "data.json": b'{"key": "value"}',
        }
        backend.add_skill(skill, resources=resources)

        # Get resources
        script = await backend.get_skill_resources("test_skill", "script.py")
        data = await backend.get_skill_resources("test_skill", "data.json")

        assert script == b"print('hello')"
        assert data == b'{"key": "value"}'

    @pytest.mark.asyncio
    async def test_get_nonexistent_resource_raises_error(self, backend: InMemorySkillBackend):
        """Test that getting nonexistent resource raises error."""
        skill = SkillMetadata(name="test_skill", description="A test skill")
        backend.add_skill(skill)

        with pytest.raises(ValueError, match="Resource not found"):
            await backend.get_skill_resources("test_skill", "nonexistent.txt")

    @pytest.mark.asyncio
    async def test_load_multiple_skills(self, backend: InMemorySkillBackend):
        """Test loading multiple skills at once."""
        skill1 = SkillMetadata(name="skill1", description="First skill")
        skill2 = SkillMetadata(name="skill2", description="Second skill")
        backend.add_skill(skill1)
        backend.add_skill(skill2)

        # Load multiple skills
        loaded = await backend.load_skills(["skill1", "skill2"])

        assert len(loaded) == 2
        assert loaded[0].name == "skill1"
        assert loaded[1].name == "skill2"
