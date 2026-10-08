"""Unit and integration tests for Profile Notes intake gate and write pipeline.

[INPUT]
- profile_notes.intake_gate: check_memory_not_garbage, filter_intake_garbage, format_profile_notes_prompt_section
- _internal.write_service: MemoryWriter
- types: SemanticMemory, EpisodicMemory, ProceduralMemory, MemoryScope

[OUTPUT]
- Pytest test cases verifying that MemoryWriter and intake gate strictly filter
  transient garbage while accepting long-term preferences and conventions.

[POS]
Harness toolkit memory test verifying Hermetic dual-layer intake gate integration.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError
from myrm_agent_harness.toolkits.memory._internal.write_service import MemoryWriter
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.profile_notes.intake_gate import (
    check_memory_not_garbage,
    filter_intake_garbage,
    format_profile_notes_prompt_section,
)
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    ConversationMemory,
    EpisodicMemory,
    MemoryScope,
    ProceduralMemory,
    SemanticMemory,
)


def test_check_memory_not_garbage_rejects_progress() -> None:
    progress_mem = SemanticMemory(content="Phase 3 completed successfully and all tests pass")
    with pytest.raises(MemoryError, match=r"Memory intake rejected: Rejected task progress milestone:"):
        check_memory_not_garbage(cast(AnyMemory, progress_mem))


def test_check_memory_not_garbage_rejects_ephemeral_numbers() -> None:
    ephemeral_mem = SemanticMemory(content="Fixed bug in PR #882 under task-4046")
    with pytest.raises(MemoryError, match=r"Memory intake rejected: Rejected ephemeral reference identifier:"):
        check_memory_not_garbage(cast(AnyMemory, ephemeral_mem))


def test_check_memory_not_garbage_rejects_transient_error() -> None:
    err_mem = SemanticMemory(content="Traceback (most recent call last):\n  File 'a.py', line 1")
    with pytest.raises(MemoryError, match=r"Memory intake rejected: Rejected transient error stacktrace"):
        check_memory_not_garbage(cast(AnyMemory, err_mem))


def test_check_memory_not_garbage_rejects_temporal_noise() -> None:
    temporal_mem = SemanticMemory(content="刚才测试了一下，发现服务有些卡顿")
    with pytest.raises(MemoryError, match=r"Memory intake rejected: Rejected ephemeral transient statement"):
        check_memory_not_garbage(cast(AnyMemory, temporal_mem))


def test_check_memory_not_garbage_accepts_valid_preferences() -> None:
    valid_mem = SemanticMemory(content="用户偏好使用 Python PEP8 规范，严禁使用 Any 类型")
    check_memory_not_garbage(cast(AnyMemory, valid_mem))


def test_filter_intake_garbage_strips_ephemeral_records() -> None:
    candidates: list[AnyMemory] = [
        cast(AnyMemory, SemanticMemory(content="用户偏好简洁且类型安全的架构设计")),
        cast(AnyMemory, SemanticMemory(content="Step 4 finished and passed all tests")),
        cast(AnyMemory, EpisodicMemory(content="Review commit a1b2c3d4e5f67890 please")),
        cast(
            AnyMemory,
            ProceduralMemory(
                content="项目规范要求单个文件不超过 400 行",
                trigger="code_review",
                action="split file if exceeding 400 lines",
            ),
        ),
    ]

    accepted, dropped = filter_intake_garbage(candidates)
    assert dropped == 2
    assert len(accepted) == 2
    contents = [getattr(m, "content", "") for m in accepted]
    assert "用户偏好简洁且类型安全的架构设计" in contents
    assert "项目规范要求单个文件不超过 400 行" in contents


def test_format_profile_notes_prompt_section_assembly() -> None:
    user_p = "母语为中文，偏好函数式纯函数与严谨类型系统"
    agent_n = "框架与业务分层架构，禁止反向依赖"

    section = format_profile_notes_prompt_section(user_p, agent_n)
    assert "## User Profile (Long-Term Preferences)" in section
    assert user_p in section
    assert "## Agent Working Notes (Domain & Project Conventions)" in section
    assert agent_n in section

    empty_section = format_profile_notes_prompt_section("", "   ")
    assert empty_section == ""


@pytest.fixture
def memory_writer() -> MemoryWriter:
    cfg = MemoryConfig(embedding_model="text-embedding-3-small", security_scan_enabled=False)
    scope = MemoryScope()

    async def _async_identity(mem: AnyMemory) -> AnyMemory:
        return mem

    async def _async_batch_identity(mems: list[SemanticMemory]) -> list[SemanticMemory]:
        return mems

    async def _async_episodic_batch(mems: list[EpisodicMemory]) -> list[EpisodicMemory]:
        return mems

    async def _async_procedural_batch(mems: list[ProceduralMemory]) -> list[ProceduralMemory]:
        return mems

    async def _async_conv_batch(mems: list[ConversationMemory]) -> list[ConversationMemory]:
        return mems

    writer = MemoryWriter(
        config=cfg,
        user_id="user_test_intake",
        scope=scope,
        namespaces=["test"],
        approval_required=False,
        bind_scope_func=lambda m: m,
        submit_pending_func=AsyncMock(return_value="pending_123"),
        store_semantic_func=cast(AsyncMock, _async_identity),
        store_episodic_func=cast(AsyncMock, _async_identity),
        store_procedural_func=cast(AsyncMock, _async_identity),
        store_semantics_batch_func=_async_batch_identity,
        store_episodics_batch_func=_async_episodic_batch,
        store_procedurals_batch_func=_async_procedural_batch,
        store_conversations_batch_func=_async_conv_batch,
        deduplicate_semantic_batch_func=_async_batch_identity,
        deduplicate_episodic_batch_func=_async_episodic_batch,
    )
    return writer


@pytest.mark.asyncio
async def test_writer_store_rejects_ephemeral_progress(memory_writer: MemoryWriter) -> None:
    bad_mem = SemanticMemory(content="Phase 2 completed and verified")
    with pytest.raises(MemoryError, match=r"Memory intake rejected: Rejected task progress milestone:"):
        await memory_writer.store(cast(AnyMemory, bad_mem))


@pytest.mark.asyncio
async def test_writer_store_accepts_valid_preference(memory_writer: MemoryWriter) -> None:
    good_mem = SemanticMemory(content="My preference is to always use concise commit messages in English")
    stored = await memory_writer.store(cast(AnyMemory, good_mem))
    assert stored.content == good_mem.content


@pytest.mark.asyncio
async def test_writer_store_batch_filters_garbage_and_keeps_valid(
    memory_writer: MemoryWriter,
) -> None:
    batch: list[AnyMemory] = [
        cast(AnyMemory, SemanticMemory(content="Fixed in commit 1234567890abcdef")),
        cast(AnyMemory, SemanticMemory(content="用户偏好深色模式主题以及 Vim 快捷键")),
        cast(AnyMemory, SemanticMemory(content="Process exited with exit code 137")),
        cast(AnyMemory, SemanticMemory(content="系统核心原则要求单文件不超过 400 行")),
    ]

    stored_batch = await memory_writer.store_batch(batch)
    assert len(stored_batch) == 2
    contents = [getattr(m, "content", "") for m in stored_batch]
    assert "用户偏好深色模式主题以及 Vim 快捷键" in contents
    assert "系统核心原则要求单文件不超过 400 行" in contents
