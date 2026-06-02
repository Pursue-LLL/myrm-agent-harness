"""Tests for Agent Profile backends (InMemory and Local)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.backends.profiles.exceptions import (
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
)
from myrm_agent_harness.backends.profiles.local_backend import LocalProfileBackend
from myrm_agent_harness.backends.profiles.memory_backend import InMemoryProfileBackend
from myrm_agent_harness.backends.profiles.types import AgentProfile


def _make_profile(
    profile_id: str = "test-agent",
    display_name: str = "Test Agent",
    **kwargs: object,
) -> AgentProfile:
    return AgentProfile(id=profile_id, display_name=display_name, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# InMemoryProfileBackend tests
# ---------------------------------------------------------------------------


class TestInMemoryProfileBackend:
    def test_create_and_get(self) -> None:
        backend = InMemoryProfileBackend()
        profile = _make_profile()
        created = backend.create_profile(profile)
        assert created.id == "test-agent"
        assert created.display_name == "Test Agent"

        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.id == "test-agent"

    def test_create_duplicate_raises(self) -> None:
        backend = InMemoryProfileBackend()
        backend.create_profile(_make_profile())
        with pytest.raises(ProfileAlreadyExistsError):
            backend.create_profile(_make_profile())

    def test_get_nonexistent_returns_none(self) -> None:
        backend = InMemoryProfileBackend()
        assert backend.get_profile("nonexistent") is None

    def test_list_profiles(self) -> None:
        backend = InMemoryProfileBackend()
        backend.create_profile(_make_profile("agent-a", "Alpha"))
        backend.create_profile(_make_profile("agent-b", "Beta"))
        profiles = backend.list_profiles()
        assert len(profiles) == 2
        ids = {p.id for p in profiles}
        assert ids == {"agent-a", "agent-b"}

    def test_update_profile(self) -> None:
        backend = InMemoryProfileBackend()
        backend.create_profile(_make_profile())
        updated_profile = _make_profile(display_name="Updated Agent")
        result = backend.update_profile(updated_profile)
        assert result.display_name == "Updated Agent"
        assert backend.get_profile("test-agent") is not None
        assert backend.get_profile("test-agent").display_name == "Updated Agent"  # type: ignore[union-attr]

    def test_update_nonexistent_raises(self) -> None:
        backend = InMemoryProfileBackend()
        with pytest.raises(ProfileNotFoundError):
            backend.update_profile(_make_profile())

    def test_delete_profile(self) -> None:
        backend = InMemoryProfileBackend()
        backend.create_profile(_make_profile())
        assert backend.delete_profile("test-agent") is True
        assert backend.get_profile("test-agent") is None

    def test_delete_nonexistent_returns_false(self) -> None:
        backend = InMemoryProfileBackend()
        assert backend.delete_profile("nonexistent") is False

    def test_list_empty(self) -> None:
        backend = InMemoryProfileBackend()
        assert backend.list_profiles() == []


# ---------------------------------------------------------------------------
# LocalProfileBackend tests
# ---------------------------------------------------------------------------


class TestLocalProfileBackend:
    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalProfileBackend:
        base_dir = str(tmp_path / "agents")
        db_path = str(tmp_path / "agents_index.db")
        return LocalProfileBackend(base_dir=base_dir, db_path=db_path)

    def test_create_and_get(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile(description="A test agent", model="gpt-4o")
        created = backend.create_profile(profile)
        assert created.id == "test-agent"
        assert created.display_name == "Test Agent"
        assert created.created_at is not None

        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.id == "test-agent"
        assert fetched.description == "A test agent"
        assert fetched.model == "gpt-4o"

    def test_create_persists_yaml_and_prompt(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile(system_prompt="You are a helpful assistant.")
        backend.create_profile(profile)

        bundle_dir = os.path.join(backend.base_dir, "test-agent")
        assert os.path.exists(os.path.join(bundle_dir, "config.yaml"))
        assert os.path.exists(os.path.join(bundle_dir, "prompt.md"))

        with open(os.path.join(bundle_dir, "prompt.md"), encoding="utf-8") as f:
            assert f.read() == "You are a helpful assistant."

    def test_create_duplicate_raises(self, backend: LocalProfileBackend) -> None:
        backend.create_profile(_make_profile())
        with pytest.raises(ProfileAlreadyExistsError):
            backend.create_profile(_make_profile())

    def test_get_nonexistent_returns_none(self, backend: LocalProfileBackend) -> None:
        assert backend.get_profile("nonexistent") is None

    def test_list_profiles(self, backend: LocalProfileBackend) -> None:
        backend.create_profile(_make_profile("agent-a", "Alpha"))
        backend.create_profile(_make_profile("agent-b", "Beta"))
        profiles = backend.list_profiles()
        assert len(profiles) == 2
        ids = {p.id for p in profiles}
        assert ids == {"agent-a", "agent-b"}

    def test_update_profile(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile()
        backend.create_profile(profile)

        profile.display_name = "Updated Agent"
        profile.description = "Updated description"
        result = backend.update_profile(profile)
        assert result.display_name == "Updated Agent"
        assert result.updated_at is not None

        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.display_name == "Updated Agent"
        assert fetched.description == "Updated description"

    def test_update_nonexistent_raises(self, backend: LocalProfileBackend) -> None:
        with pytest.raises(ProfileNotFoundError):
            backend.update_profile(_make_profile())

    def test_delete_profile(self, backend: LocalProfileBackend) -> None:
        backend.create_profile(_make_profile())
        assert backend.delete_profile("test-agent") is True
        assert backend.get_profile("test-agent") is None
        assert not os.path.exists(os.path.join(backend.base_dir, "test-agent"))

    def test_delete_nonexistent_returns_false(self, backend: LocalProfileBackend) -> None:
        assert backend.delete_profile("nonexistent") is False

    def test_list_empty(self, backend: LocalProfileBackend) -> None:
        assert backend.list_profiles() == []

    def test_system_prompt_roundtrip(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile(system_prompt="# System\nYou are an AI assistant.\n\n## Rules\n- Be helpful")
        backend.create_profile(profile)
        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.system_prompt == "# System\nYou are an AI assistant.\n\n## Rules\n- Be helpful"

    def test_metadata_roundtrip(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile(metadata={"home_directory": "/home/agent", "permissions": ["read", "write"]})
        backend.create_profile(profile)
        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.metadata["home_directory"] == "/home/agent"
        assert fetched.metadata["permissions"] == ["read", "write"]

    def test_skills_and_tools_roundtrip(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile(skills=["web_search", "code_exec"], tools_allowed=["browser", "terminal"])
        backend.create_profile(profile)
        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.skills == ["web_search", "code_exec"]
        assert fetched.tools_allowed == ["browser", "terminal"]

    def test_sync_index_on_init(self, tmp_path: Path) -> None:
        """Verify that a new backend instance picks up existing bundle dirs."""
        base_dir = str(tmp_path / "agents")
        db_path = str(tmp_path / "agents_index.db")
        backend1 = LocalProfileBackend(base_dir=base_dir, db_path=db_path)
        backend1.create_profile(_make_profile("persisted-agent", "Persisted"))

        backend2 = LocalProfileBackend(base_dir=base_dir, db_path=db_path)
        profiles = backend2.list_profiles()
        assert len(profiles) == 1
        assert profiles[0].id == "persisted-agent"

    def test_remove_prompt_on_update(self, backend: LocalProfileBackend) -> None:
        """When system_prompt is set to None, the prompt.md file should be removed."""
        profile = _make_profile(system_prompt="Initial prompt")
        backend.create_profile(profile)
        prompt_path = os.path.join(backend.base_dir, "test-agent", "prompt.md")
        assert os.path.exists(prompt_path)

        profile.system_prompt = None
        backend.update_profile(profile)
        assert not os.path.exists(prompt_path)

        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.system_prompt is None

    def test_built_in_flag(self, backend: LocalProfileBackend) -> None:
        profile = _make_profile(built_in=True)
        backend.create_profile(profile)
        fetched = backend.get_profile("test-agent")
        assert fetched is not None
        assert fetched.built_in is True
