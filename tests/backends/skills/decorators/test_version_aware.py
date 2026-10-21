"""Tests for VersionAwareSkillBackend."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.backends.skills.decorators.version_aware import (
    VersionAwareSkillBackend,
)
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def mock_base_backend():
    backend = MagicMock()
    backend.list_skills = AsyncMock()
    backend.load_skills = AsyncMock()
    backend.get_skill_content = AsyncMock(return_value="base_content")
    backend.get_skill_resources = AsyncMock(return_value=b"base_bytes")
    backend.list_skill_resources = AsyncMock(return_value=["file1"])
    return backend


@pytest.fixture
def mock_snapshot_store():
    store = MagicMock()
    store.get_active_version = AsyncMock(return_value=None)
    return store


@pytest.fixture
def backend(mock_base_backend, mock_snapshot_store):
    return VersionAwareSkillBackend(
        base_backend=mock_base_backend,
        snapshot_store=mock_snapshot_store,
    )


class TestListSkills:
    @pytest.mark.asyncio
    async def test_delegates_to_base_without_version_routing(self, backend, mock_base_backend, mock_snapshot_store):
        skills = [SkillMetadata(name="s1", description="d1")]
        mock_base_backend.list_skills.return_value = skills

        result = await backend.list_skills()

        assert result == skills
        mock_base_backend.list_skills.assert_called_once()
        mock_snapshot_store.get_active_version.assert_not_called()


class TestLoadSkills:
    @pytest.mark.asyncio
    async def test_delegates_to_base(self, backend, mock_base_backend):
        skills = [SkillMetadata(name="s1", description="d1")]
        mock_base_backend.load_skills.return_value = skills

        result = await backend.load_skills(["s1"])

        assert result == skills


class TestGetSkillContent:
    @pytest.mark.asyncio
    async def test_falls_back_to_base_without_snapshot_store(self, mock_base_backend):
        backend = VersionAwareSkillBackend(base_backend=mock_base_backend)
        mock_base_backend.get_skill_content.return_value = "base"

        result = await backend.get_skill_content("s1")

        assert result == "base"

    @pytest.mark.asyncio
    async def test_serves_active_snapshot(self, backend, mock_base_backend, mock_snapshot_store):
        mock_snapshot = MagicMock()
        mock_snapshot.content = "active_content"
        mock_snapshot.version = 3
        mock_snapshot_store.get_active_version.return_value = mock_snapshot

        result = await backend.get_skill_content("s1")

        assert result == "active_content"
        mock_base_backend.get_skill_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_base_on_no_snapshot(self, backend, mock_base_backend):
        mock_base_backend.get_skill_content.return_value = "base_content"

        result = await backend.get_skill_content("s1")

        assert result == "base_content"

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, backend, mock_base_backend, mock_snapshot_store):
        mock_snapshot_store.get_active_version.side_effect = Exception("DB Error")
        mock_base_backend.get_skill_content.return_value = "fallback"

        result = await backend.get_skill_content("s1")

        assert result == "fallback"


class TestGetSkillResources:
    @pytest.mark.asyncio
    async def test_delegates_to_base(self, backend, mock_base_backend):
        mock_base_backend.get_skill_resources.return_value = b"bytes"

        result = await backend.get_skill_resources("s1", "path")

        assert result == b"bytes"


class TestListSkillResources:
    @pytest.mark.asyncio
    async def test_delegates_to_base(self, backend, mock_base_backend):
        mock_base_backend.list_skill_resources.return_value = ["file1"]

        result = await backend.list_skill_resources("s1")

        assert result == ["file1"]
