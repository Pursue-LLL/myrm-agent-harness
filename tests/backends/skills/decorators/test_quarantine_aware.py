"""Tests for QuarantineAwareSkillBackend."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.backends.skills.decorators.quarantine_aware import (
    QuarantineAwareSkillBackend,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def mock_base_backend():
    backend = MagicMock()
    backend.list_skills = AsyncMock()
    backend.load_skills = AsyncMock()
    backend.get_skill_content = AsyncMock()
    backend.get_skill_resources = AsyncMock()
    backend.list_skill_resources = AsyncMock()
    return backend


@pytest.fixture
def mock_state_reader():
    reader = MagicMock()
    reader.is_skill_active = MagicMock(return_value=True)
    return reader


@pytest.fixture
def backend(mock_base_backend, mock_state_reader):
    return QuarantineAwareSkillBackend(
        base_backend=mock_base_backend, state_reader=mock_state_reader
    )


class TestListSkills:
    @pytest.mark.asyncio
    async def test_returns_all_active_skills(self, backend, mock_base_backend, mock_state_reader):
        skills = [
            SkillMetadata(name="s1", description="d1"),
            SkillMetadata(name="s2", description="d2"),
        ]
        mock_base_backend.list_skills.return_value = skills
        mock_state_reader.is_skill_active.return_value = True

        result = await backend.list_skills()

        assert len(result) == 2
        assert result[0].name == "s1"
        assert result[1].name == "s2"

    @pytest.mark.asyncio
    async def test_filters_inactive_skills(self, backend, mock_base_backend, mock_state_reader):
        skills = [
            SkillMetadata(name="s1", description="d1"),
            SkillMetadata(name="s2", description="d2"),
            SkillMetadata(name="s3", description="d3"),
        ]
        mock_base_backend.list_skills.return_value = skills

        def is_active(name):
            return name != "s2"

        mock_state_reader.is_skill_active.side_effect = is_active

        result = await backend.list_skills()

        assert len(result) == 2
        assert result[0].name == "s1"
        assert result[1].name == "s3"

    @pytest.mark.asyncio
    async def test_returns_empty_on_empty_input(self, backend, mock_base_backend):
        mock_base_backend.list_skills.return_value = []

        result = await backend.list_skills()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_on_state_reader_exception(
        self, backend, mock_base_backend, mock_state_reader
    ):
        skills = [SkillMetadata(name="s1", description="d1")]
        mock_base_backend.list_skills.return_value = skills
        mock_state_reader.is_skill_active.side_effect = Exception("DB Error")

        result = await backend.list_skills()

        assert len(result) == 1


class TestLoadSkills:
    @pytest.mark.asyncio
    async def test_filters_inactive_loaded_skills(self, backend, mock_base_backend, mock_state_reader):
        skills = [SkillMetadata(name="s1", description="d1")]
        mock_base_backend.load_skills.return_value = skills
        mock_state_reader.is_skill_active.return_value = False

        result = await backend.load_skills(["s1"])

        assert len(result) == 0


class TestGetSkillContent:
    @pytest.mark.asyncio
    async def test_delegates_for_active_skill(self, backend, mock_base_backend, mock_state_reader):
        mock_state_reader.is_skill_active.return_value = True
        mock_base_backend.get_skill_content.return_value = "content"

        result = await backend.get_skill_content("s1")

        assert result == "content"
        mock_base_backend.get_skill_content.assert_called_once_with("s1")

    @pytest.mark.asyncio
    async def test_raises_for_quarantined_skill(self, backend, mock_state_reader):
        mock_state_reader.is_skill_active.return_value = False

        with pytest.raises(FileNotFoundError, match="is quarantined"):
            await backend.get_skill_content("s1")


class TestGetSkillResources:
    @pytest.mark.asyncio
    async def test_delegates_for_active_skill(self, backend, mock_base_backend, mock_state_reader):
        mock_state_reader.is_skill_active.return_value = True
        mock_base_backend.get_skill_resources.return_value = b"bytes"

        result = await backend.get_skill_resources("s1", "path")

        assert result == b"bytes"

    @pytest.mark.asyncio
    async def test_raises_for_quarantined_skill(self, backend, mock_state_reader):
        mock_state_reader.is_skill_active.return_value = False

        with pytest.raises(FileNotFoundError, match="is quarantined"):
            await backend.get_skill_resources("s1", "path")


class TestListSkillResources:
    @pytest.mark.asyncio
    async def test_delegates_for_active_skill(self, backend, mock_base_backend, mock_state_reader):
        mock_state_reader.is_skill_active.return_value = True
        mock_base_backend.list_skill_resources.return_value = ["file1"]

        result = await backend.list_skill_resources("s1")

        assert result == ["file1"]

    @pytest.mark.asyncio
    async def test_returns_empty_for_quarantined_skill(self, backend, mock_state_reader):
        mock_state_reader.is_skill_active.return_value = False

        result = await backend.list_skill_resources("s1")

        assert result == []
