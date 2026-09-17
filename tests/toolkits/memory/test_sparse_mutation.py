"""Comprehensive unit test suite for Item 11: Sparse Semantic Mask Minimal Overwrite Mutation Engine.

Tests slot parsing, sparse diff action masking, informed retention, in-place synthesis,
and integration with conflict merger and memory manager.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.conflict_merger import (
    MergeAction,
    MergeRelation,
    merge_memory_candidate,
)
from myrm_agent_harness.toolkits.memory.strategies.merger import (
    DeterministicThreeStateMerger,
    MergeState,
)
from myrm_agent_harness.toolkits.memory.strategies.sparse_mutation import (
    MinimalOverwritePipeline,
    SemanticSlotParser,
    SlotAction,
    SlotKind,
    SparseSemanticMaskGenerator,
    apply_sparse_mutation,
)
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


def test_parser_and_mask_generator_internals() -> None:
    text_ex = "- item_a: val1\n- item_b: val2"
    text_cand = "- item_b: val2_new\n- item_c: val3"

    ex_slots = SemanticSlotParser.parse(text_ex)
    cand_slots = SemanticSlotParser.parse(text_cand)
    assert len(ex_slots) == 2
    assert len(cand_slots) == 2
    assert ex_slots[0].kind == SlotKind.KEY_VALUE
    assert SemanticSlotParser.is_structured(ex_slots) is True

    masks = SparseSemanticMaskGenerator.generate_mask(ex_slots, cand_slots)
    action_map = {m.slot_key: m.action for m in masks}
    assert action_map["itema"] == SlotAction.RETAIN
    assert action_map["itemb"] == SlotAction.OVERWRITE
    assert action_map["itemc"] == SlotAction.APPEND

    pipeline_res = MinimalOverwritePipeline.apply(text_ex, ex_slots, cand_slots, masks)
    assert pipeline_res.is_mutated is True
    assert pipeline_res.retained_count == 1
    assert pipeline_res.overwritten_count == 1
    assert pipeline_res.appended_count == 1


def test_key_value_slot_overwrite_and_retention() -> None:
    existing = """theme: dark
indent: 2
framework: react
linter: eslint"""

    candidate = "indent: 4"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.retained_count == 3
    assert res.overwritten_count == 1
    assert res.appended_count == 0
    assert res.removed_count == 0

    assert "theme: dark" in res.mutated_text
    assert "indent: 4" in res.mutated_text
    assert "framework: react" in res.mutated_text
    assert "linter: eslint" in res.mutated_text
    assert "indent: 2" not in res.mutated_text


def test_markdown_bullet_list_in_place_overwrite() -> None:
    existing = """- Code style: use double quotes
- Indent level: 2 spaces
- Package manager: pnpm"""

    candidate = """- Indent level: 4 spaces
- Test framework: pytest"""

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.retained_count == 2
    assert res.overwritten_count == 1
    assert res.appended_count == 1

    lines = [line.strip() for line in res.mutated_text.splitlines() if line.strip()]
    assert "- Code style: use double quotes" in lines
    assert "- Indent level: 4 spaces" in lines
    assert "- Package manager: pnpm" in lines
    assert "- Test framework: pytest" in lines


def test_clause_semicolon_mutation() -> None:
    existing = "优先使用异步编程；禁止使用全局变量；单文件代码不超过400行"
    candidate = "单文件代码不超过500行"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.retained_count == 2
    assert res.overwritten_count == 1
    assert "优先使用异步编程" in res.mutated_text
    assert "禁止使用全局变量" in res.mutated_text
    assert "单文件代码不超过500行" in res.mutated_text


def test_negation_explicit_removal() -> None:
    existing = """- UI library: tailwindcss
- State management: redux
- Bundler: vite"""

    candidate = "- 不要使用 redux"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.removed_count == 1
    assert res.retained_count == 2
    assert "tailwindcss" in res.mutated_text
    assert "vite" in res.mutated_text
    assert "redux" not in res.mutated_text


def test_unstructured_atomic_prose_bypasses_sparse_mutation() -> None:
    existing = "用户喜欢在晚上听爵士乐"
    candidate = "用户喜欢在早晨喝咖啡"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is False
    assert res.mutated_text == existing
    assert "Unstructured atomic prose" in res.summary


def test_prompt_cache_prefix_stability() -> None:
    existing = """rule 1: strictly use typing
rule 2: avoid any type
rule 3: keep file under 400 lines"""

    candidate = "rule 3: keep file under 500 lines"

    res = apply_sparse_mutation(existing, candidate)
    prefix_expected = "rule 1: strictly use typing\nrule 2: avoid any type\n"
    assert res.mutated_text.startswith(prefix_expected)


def test_deterministic_three_state_merger_integration() -> None:
    existing_mem = SemanticMemory(
        id="mem_rule_01",
        user_id="user_123",
        content="""- lang: python
- test_runner: unittest
- type_checker: mypy""",
        confidence=0.88,
    )
    candidate_content = "- test_runner: pytest"

    merger = DeterministicThreeStateMerger()
    decision = merger.evaluate(
        existing=existing_mem,
        candidate_content=candidate_content,
        similarity=0.85,
    )

    assert decision.state == MergeState.SUPPLEMENT
    assert "- test_runner: pytest" in decision.merged_content
    assert "- lang: python" in decision.merged_content
    assert "- type_checker: mypy" in decision.merged_content
    assert "补充：" not in decision.merged_content


def test_conflict_merger_pipeline_integration() -> None:
    existing_mem = SemanticMemory(
        id="mem_rule_02",
        user_id="user_123",
        content="""framework: fastapi
db: postgres
cache: memcached""",
        confidence=0.90,
    )
    candidate_mem = SemanticMemory(
        id="mem_rule_02_patch",
        user_id="user_123",
        content="cache: redis",
        confidence=0.85,
    )

    res = merge_memory_candidate(existing=existing_mem, candidate=candidate_mem)
    assert res.action == MergeAction.UPDATE
    assert res.relation == MergeRelation.SUPPLEMENT
    assert "cache: redis" in res.value
    assert "framework: fastapi" in res.value
    assert "db: postgres" in res.value
    assert res.mutation_summary is not None
    assert "1 overwritten" in res.mutation_summary


@pytest.mark.asyncio
async def test_mutations_mixin_sparse_mutate_memory() -> None:
    from myrm_agent_harness.toolkits.memory._manager.mutations import (
        MemoryManagerMutationsMixin,
    )

    class DummyManager(MemoryManagerMutationsMixin):
        def __init__(self, memory: SemanticMemory) -> None:
            self._mem = memory
            self._config = MagicMock()
            self._cache = None

        async def get_memory(self, memory_id: str) -> SemanticMemory:
            return self._mem

        def _vec(self) -> tuple[MagicMock, MagicMock]:
            return MagicMock(), MagicMock()

    initial_mem = SemanticMemory(
        id="mem_profile_01",
        user_id="user_123",
        content="""color: blue
font: fira-code
editor: neovim""",
        confidence=0.92,
    )
    mgr = DummyManager(initial_mem)

    # Patch vector memory update
    import myrm_agent_harness.toolkits.memory._manager.mutations as mut_mod
    original_update = mut_mod.update_vector_memory
    mut_mod.update_vector_memory = AsyncMock()  # type: ignore[attr-defined]

    try:
        updated = await mgr.sparse_mutate_memory(
            memory_id="mem_profile_01",
            patch_content="color: dark-ocean",
        )
        assert "color: dark-ocean" in updated.content
        assert "font: fira-code" in updated.content
        assert "editor: neovim" in updated.content
        assert updated.metadata.get("sparse_overwritten_count") == 1
        assert updated.metadata.get("sparse_retained_count") == 2
    finally:
        mut_mod.update_vector_memory = original_update  # type: ignore[attr-defined]


def test_sparse_mutation_composite_semicolon_clause_overwrite() -> None:
    existing = "- 环境配置: 生产环境; 调试模式: 关闭\n- 数据库: PostgreSQL"
    candidate = "- 调试模式: 开启"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.overwritten_count == 1
    assert res.retained_count == 2
    assert res.appended_count == 0
    assert "- 环境配置: 生产环境; 调试模式: 开启" in res.mutated_text
    assert "- 数据库: PostgreSQL" in res.mutated_text
    assert res.mutated_text.count("调试模式") == 1


def test_sparse_mutation_composite_semicolon_clause_removal() -> None:
    existing = "- 环境配置: 生产环境; 调试模式: 关闭\n- 数据库: PostgreSQL"
    candidate = "- 禁用调试模式"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.removed_count == 1
    assert res.retained_count == 2
    assert "- 环境配置: 生产环境" in res.mutated_text
    assert "调试模式" not in res.mutated_text
    assert "- 数据库: PostgreSQL" in res.mutated_text


def test_sparse_mutation_natural_language_subject_anchoring() -> None:
    existing = "- test_unit passed without error\n- test_e2e failed on timeout"
    candidate = "- test_e2e passed successfully"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.overwritten_count == 1
    assert res.retained_count == 1
    assert res.appended_count == 0
    assert "- test_unit passed without error" in res.mutated_text
    assert "- test_e2e passed successfully" in res.mutated_text
    assert "failed on timeout" not in res.mutated_text


def test_sparse_mutation_distinct_namespace_no_collision() -> None:
    existing = "- user_id must be integer\n- user_role must be admin"
    candidate = "- user_id must be uuid string"

    res = apply_sparse_mutation(existing, candidate)
    assert res.is_mutated is True
    assert res.overwritten_count == 1
    assert res.retained_count == 1
    assert "- user_id must be uuid string" in res.mutated_text
    assert "- user_role must be admin" in res.mutated_text

