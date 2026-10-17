"""lock/unlock inside a skill_manage batch: no undo record of their own, and a failed batch leaves no lock behind.

The evolution lock lives in the evolution store, not in the skill files a snapshot restores. So a batch that only
locks has nothing to undo, an undo of a mixed batch never touches the locks, and a batch that fails must put every
lock it changed back to what it was before the batch.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.skills.manage.batch_runner import (
    SKILL_BATCH_JSON_PREFIX,
    SkillManageBatchCommittedHook,
    run_skill_manage_batch,
)
from tests.agent.meta_tools.skill_manage.batch_fakes import (
    STORED,
    FailingHook,
    RecordingHook,
    make_reader,
    make_write_backend,
)

_INTEGRATION_GETTER = "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration"

_LOCK: dict[str, object] = {"action": "lock", "name": "demo"}
_UNLOCK: dict[str, object] = {"action": "unlock", "name": "demo"}
_LOCK_OTHER: dict[str, object] = {"action": "lock", "name": "other"}
_PATCH: dict[str, object] = {
    "action": "patch",
    "name": "demo",
    "old_content": "stored body",
    "new_content": "patched body",
}
_FAILING_PATCH: dict[str, object] = {
    "action": "patch",
    "name": "demo",
    "old_content": "text the skill never had",
    "new_content": "x",
}


class _FakeEvolutionStore:
    """The slice of the evolution skill store the lock actions use; every write is recorded."""

    def __init__(self, locked: dict[str, bool]) -> None:
        self.locked = dict(locked)
        self.writes: list[tuple[str, bool]] = []

    def get_skill(self, skill_id: str) -> SimpleNamespace | None:
        if skill_id not in self.locked:
            return None
        return SimpleNamespace(skill_id=skill_id, evolution_locked=self.locked[skill_id])

    async def set_evolution_lock(self, skill_id: str, *, locked: bool) -> None:
        self.writes.append((skill_id, locked))
        self.locked[skill_id] = locked


@pytest.fixture
def evolution_store() -> Iterator[_FakeEvolutionStore]:
    store = _FakeEvolutionStore({"demo": False, "other": False})
    with patch(_INTEGRATION_GETTER, return_value=SimpleNamespace(store=store)):
        yield store


async def _run(
    operations: list[dict[str, object]],
    *,
    hook: SkillManageBatchCommittedHook | None = None,
    write_backend: MagicMock | None = None,
    reader: MagicMock | None = None,
    locale: str = "en",
) -> str:
    return await run_skill_manage_batch(
        write_backend=write_backend or make_write_backend(),
        skill_backend=None,
        similarity_checker=None,
        operations=operations,
        batch_committed_hook=hook,
        snapshot_reader=reader or make_reader(STORED),
        locale=locale,
    )


async def test_a_batch_that_only_locks_leaves_no_undo_record(evolution_store: _FakeEvolutionStore) -> None:
    hook = RecordingHook()
    reader = make_reader(STORED)

    output = await _run([_LOCK], hook=hook, reader=reader)

    assert evolution_store.locked["demo"] is True
    assert "locked successfully" in output
    # Nothing on disk changed, so the Undo this would raise has nothing to restore.
    assert hook.calls == []
    assert "Batch applied successfully" not in output
    assert "batch_id=" not in output
    assert SKILL_BATCH_JSON_PREFIX not in output
    assert "Undo skill changes" not in output
    reader.get_skill_content.assert_not_called()


@pytest.mark.parametrize(
    ("locale", "note"),
    [("en", "Lock and unlock changes are not part of the undo"), ("zh-CN", "lock/unlock 的变更不在撤销范围内")],
)
async def test_a_mixed_batch_snapshots_only_the_changed_skills_and_says_the_undo_leaves_locks_alone(
    evolution_store: _FakeEvolutionStore, locale: str, note: str
) -> None:
    hook = RecordingHook()

    output = await _run([_LOCK_OTHER, _PATCH], hook=hook, locale=locale)

    assert set(hook.calls[0][1]) == {"demo"}, "a skill the batch only locked was snapshotted"
    assert evolution_store.locked["other"] is True
    assert note in output


async def test_a_batch_without_locks_does_not_mention_them(evolution_store: _FakeEvolutionStore) -> None:
    output = await _run([_PATCH], hook=RecordingHook())

    assert "Undo skill changes" in output
    assert "not part of the undo" not in output


async def test_a_failing_file_change_never_reaches_the_locks_listed_before_it(
    evolution_store: _FakeEvolutionStore,
) -> None:
    output = await _run([_LOCK, _FAILING_PATCH])

    assert output.startswith("Error: batch aborted")
    assert evolution_store.writes == [], "the lock was applied although the batch failed"


async def test_a_failing_lock_puts_the_locks_the_batch_changed_back_to_their_previous_state(
    evolution_store: _FakeEvolutionStore,
) -> None:
    evolution_store.locked["demo"] = True

    output = await _run([_UNLOCK, {"action": "lock", "name": "missing"}])

    assert output.startswith("Error: batch aborted")
    assert "not found in evolution store" in output
    assert evolution_store.locked["demo"] is True, "the failed batch left a skill the user had locked unlocked"
    assert evolution_store.writes == [("demo", False), ("demo", True)]


async def test_a_failed_batch_keeps_a_lock_the_skill_already_had(evolution_store: _FakeEvolutionStore) -> None:
    """Locking a locked skill changes nothing, so the rollback must not unlock it as the inverse of "lock"."""
    evolution_store.locked["demo"] = True

    output = await _run([_LOCK, {"action": "lock", "name": "missing"}])

    assert output.startswith("Error: batch aborted")
    assert evolution_store.locked["demo"] is True


async def test_a_persistence_failure_reverts_the_files_and_the_locks(evolution_store: _FakeEvolutionStore) -> None:
    write_backend = make_write_backend()

    output = await _run([_PATCH, _LOCK], hook=FailingHook(), write_backend=write_backend)

    assert "persistence hook failure" in output
    assert evolution_store.locked["demo"] is False, "the lock outlived the rolled-back batch"
    assert write_backend.save_skill.await_args.kwargs["content"] == STORED


async def test_locks_without_an_evolution_system_fail_the_batch_and_restore_the_files() -> None:
    write_backend = make_write_backend()

    with patch(_INTEGRATION_GETTER, return_value=None):
        output = await _run([_PATCH, _LOCK], write_backend=write_backend)

    assert output.startswith("Error: batch aborted")
    assert "not initialized" in output
    assert write_backend.save_skill.await_args.kwargs["content"] == STORED


async def test_results_are_reported_in_the_order_the_operations_were_listed(
    evolution_store: _FakeEvolutionStore,
) -> None:
    output = await _run([_LOCK, _PATCH], hook=RecordingHook())

    assert output.index("locked successfully") < output.index("patched successfully")


async def test_locking_around_an_edit_ends_with_the_lock_as_the_last_operation_left_it(
    evolution_store: _FakeEvolutionStore,
) -> None:
    hook = RecordingHook()

    output = await _run([_LOCK, _PATCH, _UNLOCK], hook=hook)

    assert evolution_store.writes == [("demo", True), ("demo", False)]
    assert evolution_store.locked["demo"] is False
    assert len(hook.calls) == 1
    assert "Undo skill changes" in output
