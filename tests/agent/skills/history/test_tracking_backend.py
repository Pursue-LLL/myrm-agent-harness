"""Integration tests for HistoryTrackingSkillWriteBackend — automatic history tracking.

Test coverage:
1. save_skill: Automatic history recording
2. delete_skill: Automatic history recording
3. write_resource: Automatic history recording
4. delete_resource: Automatic history recording
5. list_history: Delegation to backend
6. rollback_to_version: Full rollback workflow with conflict detection
7. Thread/session ID propagation
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.history import (
    HistoryTrackingSkillWriteBackend,
    JsonlHistoryBackend,
)
from myrm_agent_harness.backends.skills.creation_protocols import (
    SkillDeleteResult,
    SkillResourceWriteResult,
    SkillSaveResult,
    SkillWriteBackend,
)
from myrm_agent_harness.backends.skills.local import LocalSkillBackend


class FileSystemWriteBackend(SkillWriteBackend):
    """Dummy write backend for tests that actually writes to filesystem."""

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)

    async def save_skill(self, name: str, content: str, description: str = "") -> SkillSaveResult:
        p = self.base_path / name / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return SkillSaveResult(success=True, skill_name=name, saved_path=str(p.parent))

    async def delete_skill(self, name: str) -> SkillDeleteResult:
        p = self.base_path / name
        if p.exists():
            shutil.rmtree(p)
        return SkillDeleteResult(success=True, skill_name=name)

    async def write_resource(
        self, skill_name: str, resource_path: str, content: str
    ) -> SkillResourceWriteResult:
        p = self.base_path / skill_name / resource_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return SkillResourceWriteResult(success=True, skill_name=skill_name, resource_path=resource_path)

    async def delete_resource(self, skill_name: str, resource_path: str) -> SkillResourceWriteResult:
        p = self.base_path / skill_name / resource_path
        if p.exists():
            p.unlink()
        return SkillResourceWriteResult(success=True, skill_name=skill_name, resource_path=resource_path)


@pytest.fixture
def temp_skill_dir():
    """Create a temporary directory for skill storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_history_dir():
    """Create a temporary directory for history storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def write_backend(temp_skill_dir: Path) -> FileSystemWriteBackend:
    """Create a clean SkillWriteBackend instance."""
    return FileSystemWriteBackend(base_path=temp_skill_dir)


@pytest.fixture
def read_backend(temp_skill_dir: Path) -> LocalSkillBackend:
    """Create a clean LocalSkillBackend instance for reading."""
    return LocalSkillBackend(skills_dir=temp_skill_dir)


@pytest.fixture
def history_backend(temp_history_dir: Path) -> JsonlHistoryBackend:
    """Create a JsonlHistoryBackend instance."""
    return JsonlHistoryBackend(history_root=temp_history_dir)


@pytest.fixture
def tracking_service(
    read_backend: LocalSkillBackend,
    write_backend: FileSystemWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> HistoryTrackingSkillWriteBackend:
    """Create a HistoryTrackingSkillWriteBackend instance."""
    return HistoryTrackingSkillWriteBackend(
        read_backend=read_backend,
        write_backend=write_backend,
        history_backend=history_backend,
    )


@pytest.mark.asyncio
async def test_save_skill_creates_history(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that save_skill automatically creates history."""
    result = await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "Test"\n---\n# Test',
        thread_id="thread_001",
    )

    assert result.success
    assert result.skill_name == "test_skill"

    history = await history_backend.list_history("test_skill")
    assert len(history) == 1
    assert history[0].action == "save"
    assert history[0].thread_id == "thread_001"
    assert history[0].prev_content is None
    assert history[0].new_content is not None


@pytest.mark.asyncio
async def test_save_skill_update_records_prev_content(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that updating a skill records both prev and new content."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V1"\n---\n# Version 1',
    )

    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V2"\n---\n# Version 2',
    )

    history = await history_backend.list_history("test_skill")
    assert len(history) == 2

    assert history[0].action == "save"
    assert history[0].prev_content is not None
    assert "Version 1" in history[0].prev_content
    assert "Version 2" in history[0].new_content

    assert history[1].action == "save"
    assert history[1].prev_content is None


@pytest.mark.asyncio
async def test_delete_skill_creates_history(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that delete_skill records history."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "Test"\n---\n# Test',
    )

    result = await tracking_service.delete_skill(
        name="test_skill",
        thread_id="thread_delete",
    )

    assert result.success

    history = await history_backend.list_history("test_skill")
    assert len(history) == 2

    assert history[0].action == "delete"
    assert history[0].thread_id == "thread_delete"
    assert history[0].prev_content is not None
    assert history[0].new_content is None


@pytest.mark.asyncio
async def test_rollback_to_version(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test rollback_to_version restores previous content."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V1"\n---\n# Version 1',
    )

    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V2"\n---\n# Version 2',
    )

    rollback_result = await tracking_service.rollback_to_version(
        skill_name="test_skill",
        history_index=-1,
        thread_id="thread_rollback",
    )

    assert rollback_result.success
    assert rollback_result.skill_name == "test_skill"

    current_content = await tracking_service._read.get_skill_content("test_skill")
    assert "Version 1" in current_content

    history = await history_backend.list_history("test_skill")
    assert len(history) == 4

    assert history[0].action == "rollback"
    assert history[0].thread_id == "thread_rollback"


@pytest.mark.asyncio
async def test_rollback_conflict_detection(
    tracking_service: HistoryTrackingSkillWriteBackend,
) -> None:
    """Test that rollback detects conflicts (newer modifications)."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V1"\n---\n# Version 1',
    )

    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V2"\n---\n# Version 2',
    )

    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "V3"\n---\n# Version 3',
    )

    rollback_result = await tracking_service.rollback_to_version(
        skill_name="test_skill",
        history_index=-2,
    )

    assert not rollback_result.success
    assert "conflict" in rollback_result.error.lower()


@pytest.mark.asyncio
async def test_list_history_delegation(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that list_history delegates to backend."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "Test"\n---\n# Test',
    )

    service_history = await tracking_service.list_history("test_skill")
    backend_history = await history_backend.list_history("test_skill")

    assert len(service_history) == len(backend_history)
    assert service_history[0].action == backend_history[0].action


@pytest.mark.asyncio
async def test_write_resource_creates_history(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that write_resource records history."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "Test"\n---\n# Test',
    )

    result = await tracking_service.write_resource(
        skill_name="test_skill",
        resource_path="scripts/helper.py",
        content="print('hello')",
        thread_id="thread_resource",
    )

    assert result.success

    history = await history_backend.list_history("test_skill")
    assert len(history) == 2

    assert history[0].action == "write_file"
    assert "scripts/helper.py" in history[0].file_path
    assert history[0].thread_id == "thread_resource"
    assert history[0].new_content == "print('hello')"


@pytest.mark.asyncio
async def test_delete_resource_creates_history(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that delete_resource records history."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "Test"\n---\n# Test',
    )

    await tracking_service.write_resource(
        skill_name="test_skill",
        resource_path="scripts/helper.py",
        content="print('hello')",
    )

    result = await tracking_service.delete_resource(
        skill_name="test_skill",
        resource_path="scripts/helper.py",
        thread_id="thread_delete_res",
    )

    assert result.success

    history = await history_backend.list_history("test_skill")
    assert len(history) == 3

    assert history[0].action == "remove_file"
    assert "scripts/helper.py" in history[0].file_path
    assert history[0].thread_id == "thread_delete_res"
    assert history[0].prev_content == "print('hello')"
    assert history[0].new_content is None


@pytest.mark.asyncio
async def test_thread_id_propagation(
    tracking_service: HistoryTrackingSkillWriteBackend,
    history_backend: JsonlHistoryBackend,
) -> None:
    """Test that thread_id is properly propagated to history records."""
    await tracking_service.save_skill(
        name="test_skill",
        content='---\nname: test_skill\ndescription: "Test"\n---\n# Test',
        thread_id="thread_abc",
        session_id="session_xyz",
        request_id="request_123",
    )

    history = await history_backend.list_history("test_skill")
    assert len(history) == 1

    record = history[0]
    assert record.thread_id == "thread_abc"
    assert record.session_id == "session_xyz"
    assert record.request_id == "request_123"


@pytest.mark.asyncio
async def test_rollback_with_no_history(
    tracking_service: HistoryTrackingSkillWriteBackend,
) -> None:
    """Test rollback when no history exists."""
    result = await tracking_service.rollback_to_version(
        skill_name="nonexistent_skill",
        history_index=-1,
    )

    assert not result.success
    assert "no history" in result.error.lower()
