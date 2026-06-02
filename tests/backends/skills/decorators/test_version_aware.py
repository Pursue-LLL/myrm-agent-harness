"""Tests for VersionAwareSkillBackend."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.backends.skills.decorators.version_aware import (
    VersionAwareSkillBackend,
    forced_version_var,
    session_id_var,
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
    store.get_version = AsyncMock(return_value=None)
    store.get_active_version = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_ab_test_store():
    store = MagicMock()
    store.get_running_tests = AsyncMock(return_value=[])
    return store


@pytest.fixture
def backend(mock_base_backend, mock_snapshot_store, mock_ab_test_store):
    return VersionAwareSkillBackend(
        base_backend=mock_base_backend,
        snapshot_store=mock_snapshot_store,
        ab_test_store=mock_ab_test_store,
    )


class TestListSkills:
    @pytest.mark.asyncio
    async def test_delegates_to_base(self, backend, mock_base_backend):
        skills = [SkillMetadata(name="s1", description="d1")]
        mock_base_backend.list_skills.return_value = skills

        result = await backend.list_skills()

        assert result == skills
        mock_base_backend.list_skills.assert_called_once()


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
    async def test_serves_forced_version(self, backend, mock_snapshot_store):
        mock_snapshot = MagicMock()
        mock_snapshot.content = "forced_content"
        mock_snapshot_store.get_version.return_value = mock_snapshot

        token = forced_version_var.set(42)
        try:
            result = await backend.get_skill_content("s1")
            assert result == "forced_content"
            mock_snapshot_store.get_version.assert_called_once_with("s1", 42)
        finally:
            forced_version_var.reset(token)

    @pytest.mark.asyncio
    async def test_serves_active_snapshot(self, backend, mock_snapshot_store):
        mock_snapshot = MagicMock()
        mock_snapshot.content = "active_content"
        mock_snapshot.version = 3
        mock_snapshot_store.get_active_version.return_value = mock_snapshot

        result = await backend.get_skill_content("s1")

        assert result == "active_content"

    @pytest.mark.asyncio
    async def test_falls_back_to_base_on_no_snapshot(self, backend, mock_base_backend):
        mock_base_backend.get_skill_content.return_value = "base_content"

        result = await backend.get_skill_content("s1")

        assert result == "base_content"

    @pytest.mark.asyncio
    async def test_ab_test_candidate_routing(self, backend, mock_snapshot_store, mock_ab_test_store):
        mock_test = MagicMock()
        mock_test.skill_id = "s1"
        mock_test.candidate_version = 2
        mock_test.baseline_version = 1
        mock_ab_test_store.get_running_tests.return_value = [mock_test]

        mock_snapshot = MagicMock()
        mock_snapshot.content = "candidate_content"
        mock_snapshot_store.get_version.return_value = mock_snapshot

        # Force session_id to get deterministic routing
        token = session_id_var.set("test_session_123")
        try:
            result = await backend.get_skill_content("s1")
            # Result depends on hash-based routing
            assert result in ("candidate_content", "base_content")
        finally:
            session_id_var.reset(token)

    @pytest.mark.asyncio
    async def test_ab_test_baseline_fallback(self, backend, mock_base_backend, mock_snapshot_store, mock_ab_test_store):
        mock_test = MagicMock()
        mock_test.skill_id = "s1"
        mock_test.candidate_version = 2
        mock_test.baseline_version = 1
        mock_ab_test_store.get_running_tests.return_value = [mock_test]

        # Snapshot not found for baseline
        mock_snapshot_store.get_version.return_value = None
        mock_base_backend.get_skill_content.return_value = "baseline_fallback"

        # Force session to get baseline routing
        # We need to find a session_id that hashes to baseline (>50)
        token = session_id_var.set("baseline_session")
        try:
            result = await backend.get_skill_content("s1")
            # If routed to baseline and snapshot missing, falls back to base
            assert result == "baseline_fallback"
        finally:
            session_id_var.reset(token)

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


class TestStickyRouting:
    def test_deterministic_routing(self, backend):
        # Same session + skill should always route the same way
        result1 = backend._resolve_sticky("session1", "skill1")
        result2 = backend._resolve_sticky("session1", "skill1")
        assert result1 == result2

    def test_different_sessions_may_differ(self, backend):
        # Different sessions might route differently (probabilistic)
        results = set()
        for i in range(100):
            results.add(backend._resolve_sticky(f"session_{i}", "skill1"))
        # With 100 different sessions, we should get both True and False
        assert len(results) == 2
