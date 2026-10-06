# [POS] tests/toolkits/memory/test_memory_provenance_batch.py
# [INPUT] provenance_batch (types, isolator, provenance_linker), memory.types
# [OUTPUT] test_batch_learn_namespace_isolation_formatting_and_parsing, test_batch_learn_pipeline_partitions_and_isolates, test_skill_provenance_linker_creation_and_integrity_verification, test_anchor_provenance_link_to_procedural_memory

import pytest

from myrm_agent_harness.toolkits.memory.provenance_batch import (
    BatchLearnItem,
    BatchLearnNamespaceIsolator,
    ExtractionProvenanceLink,
    SkillProvenanceLinker,
    ToolExecutionTrace,
)
from myrm_agent_harness.toolkits.memory.types import ProceduralMemory


def test_batch_learn_namespace_isolation_formatting_and_parsing() -> None:
    """Verify deterministic namespaced ID generation, idempotence, and safe parsing."""
    isolator = BatchLearnNamespaceIsolator()

    # Standard formatting
    formatted = isolator.format_namespaced_id(
        namespace="agent:coder",
        scope_level="agent",
        raw_id="rule-fastapi-cors",
    )
    assert formatted == "agent:coder::agent::rule-fastapi-cors"

    # Idempotence check
    reformatted = isolator.format_namespaced_id(
        namespace="agent:coder",
        scope_level="agent",
        raw_id=formatted,
    )
    assert reformatted == formatted

    # Deconstruction
    ns, scope, raw = isolator.parse_namespaced_id(formatted)
    assert ns == "agent:coder"
    assert scope == "agent"
    assert raw == "rule-fastapi-cors"

    # Empty validation
    with pytest.raises(ValueError):
        isolator.format_namespaced_id(namespace="", scope_level="agent", raw_id="1")


def test_batch_learn_pipeline_partitions_and_isolates() -> None:
    """Verify batch learning partitions agent-private and shared memories distinctly."""
    isolator = BatchLearnNamespaceIsolator()

    items = [
        BatchLearnItem(
            raw_id="item-1",
            content="Private docker proxy trick",
            namespace="agent:worker-1",
            scope_level="agent",
            provenance_link=ExtractionProvenanceLink(
                conversation_id="conv-1",
                trigger_prompt_snippet="How to configure docker proxy?",
            ),
        ),
        BatchLearnItem(
            raw_id="item-2",
            content="Shared team coding guideline",
            namespace="global",
            scope_level="shared",
            provenance_link=None,
        ),
    ]

    result = isolator.isolate_batch(items)
    assert result.total_items == 2
    assert result.has_provenance_count == 1
    assert result.namespaced_items[0].namespaced_id == "agent:worker-1::agent::item-1"
    assert result.namespaced_items[1].namespaced_id == "global::shared::item-2"


def test_skill_provenance_linker_creation_and_integrity_verification() -> None:
    """Verify provenance links capture tool traces and validate physical integrity."""
    linker = SkillProvenanceLinker()

    tool_traces = [
        ToolExecutionTrace(
            tool_name="bash",
            tool_call_id="call_123",
            input_args_summary="pytest tests/unit",
            output_evidence_snippet="10 passed in 1.2s",
            status="success",
            duration_ms=1200.0,
        )
    ]

    link = linker.create_provenance_link(
        conversation_id="session-abc",
        turn_index=3,
        trigger_prompt="请帮我跑一下测试并总结避坑指南",
        tool_traces=tool_traces,
        counterexample="直接使用全局 pytest 会因缺少环境变量失败",
        confidence_score=0.95,
    )

    assert link.conversation_id == "session-abc"
    assert link.turn_index == 3
    assert len(link.tool_traces) == 1
    assert link.tool_traces[0].tool_name == "bash"

    is_valid, error = linker.verify_provenance_link(link)
    assert is_valid is True
    assert error is None

    # Invalid empty prompt
    with pytest.raises(ValueError):
        linker.create_provenance_link(conversation_id="conv-x", trigger_prompt="")


def test_anchor_provenance_link_to_procedural_memory() -> None:
    """Verify linking provenance anchors into ProceduralMemory metadata and evidence."""
    linker = SkillProvenanceLinker()

    tool_traces = [
        ToolExecutionTrace(
            tool_name="git",
            tool_call_id="call_git_status",
            input_args_summary="git status",
            output_evidence_snippet="clean working directory",
            status="success",
            duration_ms=45.0,
        )
    ]

    link = linker.create_provenance_link(
        conversation_id="conv-git-flow",
        turn_index=2,
        trigger_prompt="提交前必须保持工作区干净",
        tool_traces=tool_traces,
    )

    proc_mem = ProceduralMemory(
        trigger="在执行 git push 之前",
        action="运行 git status 检查未跟踪文件",
        reasoning="防止将临时调试文件误推送到远端仓库",
    )

    anchored = linker.anchor_to_memory(proc_mem, link)
    assert anchored.metadata["provenance_link_id"] == link.link_id
    assert anchored.metadata["provenance_conversation_id"] == "conv-git-flow"
    assert anchored.metadata["provenance_turn_index"] == 2
    assert len(anchored.evidence) == 1
    assert anchored.evidence[0].source_id == "tool_trace:git"
    assert anchored.evidence[0].message_id == "call_git_status"
