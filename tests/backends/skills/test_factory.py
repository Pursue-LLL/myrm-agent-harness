"""Tests for SkillBackend factory methods."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.backends.skills.factory import SkillBackend
from myrm_agent_harness.backends.skills.types import SkillTrust
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend


def test_local_creates_local_backend(tmp_path: Path):
    """SkillBackend.local() should create a LocalSkillBackend."""
    from myrm_agent_harness.backends.skills import LocalSkillBackend

    backend = SkillBackend.local(tmp_path)
    assert isinstance(backend, LocalSkillBackend)


def test_storage_creates_storage_backend(tmp_path: Path):
    """SkillBackend.storage() should create a StorageSkillBackend."""
    from myrm_agent_harness.backends.skills import StorageSkillBackend

    storage = LocalStorageBackend(str(tmp_path))
    backend = SkillBackend.storage(storage, skills_prefix="/skills")
    assert isinstance(backend, StorageSkillBackend)


def test_storage_with_default_trust(tmp_path: Path):
    """SkillBackend.storage() should pass default_trust to StorageSkillBackend."""
    from myrm_agent_harness.backends.skills import StorageSkillBackend

    storage = LocalStorageBackend(str(tmp_path))
    backend = SkillBackend.storage(storage, skills_prefix="/skills", default_trust=SkillTrust.TRUSTED)
    assert isinstance(backend, StorageSkillBackend)
    assert backend._default_trust == SkillTrust.TRUSTED


def test_storage_without_default_trust_uses_installed(tmp_path: Path):
    """SkillBackend.storage() without default_trust should default to INSTALLED."""
    from myrm_agent_harness.backends.skills import StorageSkillBackend

    storage = LocalStorageBackend(str(tmp_path))
    backend = SkillBackend.storage(storage, skills_prefix="/skills")
    assert isinstance(backend, StorageSkillBackend)
    assert backend._default_trust == SkillTrust.INSTALLED


def test_composite_creates_composite_backend(tmp_path: Path):
    """SkillBackend.composite() should create a CompositeSkillBackend."""
    from myrm_agent_harness.backends.skills import CompositeSkillBackend

    local = SkillBackend.local(tmp_path)
    backend = SkillBackend.composite(routes={"/user/": local}, default=local)
    assert isinstance(backend, CompositeSkillBackend)
