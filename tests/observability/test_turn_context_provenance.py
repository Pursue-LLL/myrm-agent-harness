"""
[INPUT]: TurnContextManifestBuilder, InjectionSourceKind, TurnContextInjectionManifest.
[OUTPUT]: Pytest test cases verifying injection manifest generation, sha256 fingerprints, and cross-turn diffing.
[POS]: myrm-agent-harness/tests/observability/test_turn_context_provenance.py
"""

import hashlib
import pytest

from myrm_agent_harness.observability.turn_context_provenance import (
    InjectionSourceKind,
    TurnContextChunk,
    TurnContextInjectionManifest,
    TurnContextManifestBuilder,
    TurnProvenanceDiffItem,
)


def test_turn_context_manifest_builder_basic_construction() -> None:
    builder = TurnContextManifestBuilder()

    sys_text = "You are a specialized code refactoring assistant."
    mem_text = "User preferences: Strict PEP8 and type annotations."
    skill_text = "Skill: execute_bash_command with timeout safety."

    manifest = (
        builder.add_chunk(
            source_id="system_prompt_base",
            kind=InjectionSourceKind.SYSTEM_PROMPT,
            content=sys_text,
            estimated_tokens=15,
        )
        .add_chunk(
            source_id="mem_user_pref_001",
            kind=InjectionSourceKind.MEMORY,
            content=mem_text,
            estimated_tokens=12,
        )
        .add_chunk(
            source_id="skill_bash",
            kind=InjectionSourceKind.SKILL,
            content=skill_text,
            estimated_tokens=10,
        )
        .build(
            session_id="sess_provenance_01",
            turn_id="turn_001",
            model_snapshot_id="claude-3-7-sonnet-20250219",
        )
    )

    assert isinstance(manifest, TurnContextInjectionManifest)
    assert manifest.session_id == "sess_provenance_01"
    assert manifest.turn_id == "turn_001"
    assert manifest.model_snapshot_id == "claude-3-7-sonnet-20250219"
    assert manifest.total_tokens == 37
    assert manifest.total_chars == len(sys_text) + len(mem_text) + len(skill_text)
    assert len(manifest.chunks) == 3

    # 验证第一个 chunk 结构与 SHA256 指纹
    c0 = manifest.chunks[0]
    assert c0.source_id == "system_prompt_base"
    assert c0.kind == InjectionSourceKind.SYSTEM_PROMPT
    assert c0.order_index == 0
    expected_hash = hashlib.sha256(sys_text.encode("utf-8")).hexdigest()
    assert c0.content_sha256 == expected_hash

    # 验证序列化契约
    data = manifest.to_dict()
    assert data["session_id"] == "sess_provenance_01"
    assert len(data["chunks"]) == 3


def test_turn_context_cross_turn_diff() -> None:
    # 构造 Turn 1
    builder_t1 = TurnContextManifestBuilder()
    m1 = (
        builder_t1.add_chunk(
            source_id="sys_prompt",
            kind=InjectionSourceKind.SYSTEM_PROMPT,
            content="Initial system prompt v1",
            estimated_tokens=10,
        )
        .add_chunk(
            source_id="mem_constant",
            kind=InjectionSourceKind.MEMORY,
            content="Memory that never changes",
            estimated_tokens=8,
        )
        .add_chunk(
            source_id="skill_old_bash",
            kind=InjectionSourceKind.SKILL,
            content="Old bash tool",
            estimated_tokens=6,
        )
        .build("sess_1", "turn_1")
    )

    # 构造 Turn 2 (sys 修改, mem_constant 不变, skill_old_bash 删除, skill_new_python 新增)
    builder_t2 = TurnContextManifestBuilder()
    m2 = (
        builder_t2.add_chunk(
            source_id="sys_prompt",
            kind=InjectionSourceKind.SYSTEM_PROMPT,
            content="Modified system prompt v2 with extra rules",
            estimated_tokens=16,
        )
        .add_chunk(
            source_id="mem_constant",
            kind=InjectionSourceKind.MEMORY,
            content="Memory that never changes",
            estimated_tokens=8,
        )
        .add_chunk(
            source_id="skill_new_python",
            kind=InjectionSourceKind.SKILL,
            content="New Python execution tool",
            estimated_tokens=14,
        )
        .build("sess_1", "turn_2")
    )

    diffs = TurnContextManifestBuilder.diff_manifests(m1, m2)
    assert len(diffs) == 4

    diff_map = {d.source_id: d for d in diffs}

    # 1. sys_prompt 发生变化
    assert "sys_prompt" in diff_map
    assert diff_map["sys_prompt"].diff_type == "MODIFIED"
    assert diff_map["sys_prompt"].token_delta == 6  # 16 - 10

    # 2. mem_constant 保持不变
    assert "mem_constant" in diff_map
    assert diff_map["mem_constant"].diff_type == "UNCHANGED"
    assert diff_map["mem_constant"].token_delta == 0

    # 3. skill_old_bash 被移除
    assert "skill_old_bash" in diff_map
    assert diff_map["skill_old_bash"].diff_type == "REMOVED"
    assert diff_map["skill_old_bash"].token_delta == -6

    # 4. skill_new_python 新增
    assert "skill_new_python" in diff_map
    assert diff_map["skill_new_python"].diff_type == "ADDED"
    assert diff_map["skill_new_python"].token_delta == 14
