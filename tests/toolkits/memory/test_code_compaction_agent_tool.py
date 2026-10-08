"""Unit tests for token-budget-aware code memory compaction tool and MemoryManager mixin."""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.memory._manager.code_compaction import (
    MemoryManagerCodeCompactionMixin,
)
from myrm_agent_harness.toolkits.memory.compaction.tool import (
    create_code_memory_compaction_tool,
)
from myrm_agent_harness.toolkits.memory.compaction.types import (
    CodeAbstractionLevel,
    CodeBlockItem,
)


class DummyMemoryManager(MemoryManagerCodeCompactionMixin):
    """Dummy MemoryManager subclass for testing code compaction mixin."""

    def __init__(self) -> None:
        self.user_id = "test_user"


SAMPLE_PYTHON_CODE = '''"""Sample module for data processing."""

def process_batch(items: list[int], threshold: int = 10) -> list[int]:
    """Filter and square items exceeding threshold."""
    result = []
    for x in items:
        if x > threshold:
            computed = x * x
            result.append(computed)
    return result


class BatchProcessor:
    """Class to process and summarize batches."""

    def __init__(self, name: str) -> None:
        self.name = name

    def execute(self, payload: list[int]) -> dict[str, int]:
        processed = process_batch(payload)
        return {"count": len(processed)}
'''


def test_create_code_memory_compaction_tool_metadata() -> None:
    tool = create_code_memory_compaction_tool()
    assert tool.name == "compact_code_memory"
    assert "token budget" in tool.description.lower() or "compact" in tool.description.lower()


def test_compaction_tool_fits_within_small_budget() -> None:
    tool = create_code_memory_compaction_tool()
    # Call tool with very small budget, forcing L1 signature compaction
    raw_result = tool.invoke(
        {
            "source_code": SAMPLE_PYTHON_CODE,
            "file_path": "processor.py",
            "token_budget": 50,
            "relevance_score": 0.5,
        }
    )
    assert isinstance(raw_result, str)
    data = json.loads(raw_result)

    assert data["file_path"] == "processor.py"
    assert data["abstraction_level"] in ("L1_SIGNATURES", "L2_CONTROL_FLOW")
    assert "def process_batch" in data["compacted_code"]
    assert data["compacted_tokens"] <= 50 or data["tokens_saved"] > 0
    assert data["tokens_saved"] >= 0
    assert 0.0 <= data["compression_ratio"] <= 100.0


def test_compaction_tool_preserves_full_source_with_generous_budget() -> None:
    tool = create_code_memory_compaction_tool()
    # Call tool with generous budget
    raw_result = tool.invoke(
        {
            "source_code": SAMPLE_PYTHON_CODE,
            "file_path": "processor.py",
            "token_budget": 2000,
            "relevance_score": 1.0,
        }
    )
    data = json.loads(raw_result)
    assert data["abstraction_level"] == "L3_FULL_SOURCE"
    assert "computed = x * x" in data["compacted_code"]
    assert data["compacted_tokens"] == data["original_tokens"]
    assert data["tokens_saved"] == 0


def test_compaction_tool_empty_source() -> None:
    tool = create_code_memory_compaction_tool()
    raw_result = tool.invoke(
        {
            "source_code": "",
            "file_path": "empty.py",
            "token_budget": 100,
            "relevance_score": 1.0,
        }
    )
    data = json.loads(raw_result)
    assert data["compacted_code"] == ""
    assert data["tokens_saved"] == 0


def test_memory_manager_mixin_compact_item() -> None:
    manager = DummyMemoryManager()
    compacted = manager.compact_code_memory_item(
        SAMPLE_PYTHON_CODE,
        file_path="processor.py",
        token_budget=50,
        relevance_score=0.4,
    )
    assert compacted is not None
    assert compacted.file_path == "processor.py"
    assert compacted.abstraction_level in (
        CodeAbstractionLevel.L1_SIGNATURES,
        CodeAbstractionLevel.L2_CONTROL_FLOW,
    )
    assert "process_batch" in compacted.content


def test_memory_manager_mixin_compact_batch() -> None:
    manager = DummyMemoryManager()
    items = [
        CodeBlockItem(
            file_path="high_priority.py",
            source_code=SAMPLE_PYTHON_CODE,
            relevance_score=0.95,
        ),
        CodeBlockItem(
            file_path="low_priority.py",
            source_code=SAMPLE_PYTHON_CODE,
            relevance_score=0.1,
        ),
    ]

    result = manager.compact_code_memory_batch(items, token_budget=150)
    assert result.total_compacted_tokens <= 150
    assert len(result.compacted_blocks) == 2

    # High priority item should have equal or higher detail than low priority item
    high_block = next(b for b in result.compacted_blocks if b.file_path == "high_priority.py")
    low_block = next(b for b in result.compacted_blocks if b.file_path == "low_priority.py")
    assert high_block.abstraction_level.value >= low_block.abstraction_level.value
