"""
[POS] tests/unit/test_governed_write_safety_suite.py
Unit tests for String-Is-Never-Authority Governed Write Safety Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.governed_write_safety import (
    GovernedWriteSafetyFacade,
    WriteProposalStatus,
)


@pytest.fixture
def facade() -> GovernedWriteSafetyFacade:
    return GovernedWriteSafetyFacade()


def test_opaque_id_shielding(facade: GovernedWriteSafetyFacade) -> None:
    raw_path = "/workspace/project/src/sensitive_logic.py"
    opaque_id = facade.register_opaque_file(raw_path)

    assert opaque_id.startswith("@file_")
    assert facade.resolve_path(opaque_id) == raw_path

    # Unregistered opaque ID returns None
    assert facade.resolve_path("@file_nonexistent") is None


def test_governed_write_happy_path(facade: GovernedWriteSafetyFacade) -> None:
    raw_path = "/workspace/project/config.yaml"
    opaque_id = facade.register_opaque_file(raw_path)

    initial_content = "server:\n  port: 8080\n"
    candidate_content = "server:\n  port: 9000\n"

    # 1. Propose edit
    prop = facade.propose_edit(
        opaque_file_id=opaque_id,
        current_disk_content=initial_content,
        candidate_content=candidate_content,
    )
    assert prop.status == WriteProposalStatus.PROPOSED
    assert prop.base_content_hash != prop.candidate_content_hash

    # 2. Approve proposal
    lease_token = facade.approve_edit(prop.proposal_id)
    assert lease_token.startswith("lease-tok-")

    # 3. Commit write
    disk_store: dict[str, str] = {raw_path: initial_content}

    def write_fn(new_text: str) -> str:
        disk_store[raw_path] = new_text
        return new_text

    result = facade.commit_edit(
        proposal_id=prop.proposal_id,
        lease_token=lease_token,
        current_disk_content=disk_store[raw_path],
        write_executor=write_fn,
    )

    assert result.success is True
    assert result.status == WriteProposalStatus.COMMITTED
    assert result.pre_image_snapshot_id is not None
    assert disk_store[raw_path] == candidate_content

    # 4. Inspect captured pre-image snapshot
    snap = facade.get_snapshot(result.pre_image_snapshot_id)
    assert snap is not None
    assert snap.opaque_file_id == opaque_id
    assert snap.content_preview == initial_content


def test_stale_rejection_on_concurrent_modification(
    facade: GovernedWriteSafetyFacade,
) -> None:
    raw_path = "/workspace/project/shared_notes.txt"
    opaque_id = facade.register_opaque_file(raw_path)

    user_base_content = "Line 1: Note from morning"
    agent_candidate_content = "Line 1: Note from morning\nLine 2: AI appended note"

    # 1. Propose edit based on original morning note
    prop = facade.propose_edit(
        opaque_file_id=opaque_id,
        current_disk_content=user_base_content,
        candidate_content=agent_candidate_content,
    )
    lease_token = facade.approve_edit(prop.proposal_id)

    # 2. Simulate concurrent user modification on disk before commit
    concurrent_disk_content = "Line 1: Note from morning (edited by user at 2pm)"

    write_called = False

    def write_fn(new_text: str) -> str:
        nonlocal write_called
        write_called = True
        return new_text

    # 3. Attempt commit - MUST be rejected as STALE!
    result = facade.commit_edit(
        proposal_id=prop.proposal_id,
        lease_token=lease_token,
        current_disk_content=concurrent_disk_content,
        write_executor=write_fn,
    )

    assert result.success is False
    assert result.status == WriteProposalStatus.STALE_REJECTED
    assert write_called is False  # Never wrote to disk!
    assert result.conflict_bundle is not None
    assert "concurrent modification" in result.conflict_bundle.reason.lower()


def test_anti_overclaim_integrity_check(facade: GovernedWriteSafetyFacade) -> None:
    raw_path = "/workspace/project/script.py"
    opaque_id = facade.register_opaque_file(raw_path)

    base_content = "print('hello')"
    candidate_content = "print('world')"

    prop = facade.propose_edit(
        opaque_file_id=opaque_id,
        current_disk_content=base_content,
        candidate_content=candidate_content,
    )
    lease_token = facade.approve_edit(prop.proposal_id)

    # Defective write executor that silently writes corrupted/different text
    def buggy_write_fn(new_text: str) -> str:
        return "print('corrupted')"

    result = facade.commit_edit(
        proposal_id=prop.proposal_id,
        lease_token=lease_token,
        current_disk_content=base_content,
        write_executor=buggy_write_fn,
    )

    assert result.success is False
    assert "integrity check failed" in (result.error_message or "").lower()
