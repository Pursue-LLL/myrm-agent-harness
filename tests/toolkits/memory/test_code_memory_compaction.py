# [POS] tests/toolkits/memory/test_code_memory_compaction.py
# [INPUT] CodeAbstractionLevel, CodeBlockItem, CompactionConfig, CodeSkeletonExtractor, CodeMemoryBudgetCompactor
# [OUTPUT] pytest test suite for Token-Budget-Aware Code Memory Compaction Engine

"""Unit tests for Token-Budget-Aware Codebase Semantic Memory Compaction Engine."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.compaction import (
    CodeAbstractionLevel,
    CodeBlockItem,
    CodeMemoryBudgetCompactor,
    CodeSkeletonExtractor,
    CompactionConfig,
)


def test_l1_signature_extraction_python() -> None:
    """Verify that L1 abstraction retains signatures and types while collapsing bodies."""
    source_code = """
class DataPipeline(BasePipeline):
    \"\"\"Process stream data into memory buffers.\"\"\"
    buffer_size: int = 1024

    def __init__(self, name: str, timeout: float = 30.0) -> None:
        self.name = name
        self.timeout = timeout
        self._internal_cache: dict[str, str] = {}
        print("initializing pipeline...")

    async def ingest_batch(self, records: list[dict[str, str]]) -> int:
        count = 0
        for r in records:
            count += len(r)
        return count

    def _internal_helper(self, token: str) -> bool:
        return token.startswith("test_")
"""
    l1_code = CodeSkeletonExtractor.extract_skeleton(
        source_code=source_code,
        level=CodeAbstractionLevel.L1_SIGNATURES,
        strip_private=False,
    )

    assert "class DataPipeline" in l1_code
    assert "def __init__(self, name: str, timeout: float" in l1_code
    assert ") -> None:" in l1_code
    assert "async def ingest_batch(self, records: list[dict[str, str]]) -> int:" in l1_code
    # Bodies should be collapsed with Ellipsis
    assert "..." in l1_code
    assert "initializing pipeline..." not in l1_code
    assert "count += len(r)" not in l1_code


def test_l2_control_flow_extraction_python() -> None:
    """Verify that L2 abstraction retains docstrings, conditionals, and exception blocks."""
    source_code = """
def authenticate_and_dispatch(user_id: str, payload: dict[str, str]) -> bool:
    \"\"\"Check credentials and execute action securely.\"\"\"
    if not user_id:
        raise ValueError("User ID cannot be empty")
    try:
        token = payload.get("token")
        for item in payload.values():
            compute_heavy_hash(item)
        return True
    except ConnectionError:
        raise RuntimeError("Service unreachable")
    return False
"""
    l2_code = CodeSkeletonExtractor.extract_skeleton(
        source_code=source_code,
        level=CodeAbstractionLevel.L2_CONTROL_FLOW,
        strip_private=False,
    )

    assert "Check credentials and execute action securely." in l2_code
    assert "if not user_id:" in l2_code
    assert "raise ValueError('User ID cannot be empty')" in l2_code or 'raise ValueError("User ID cannot be empty")' in l2_code
    assert "try:" in l2_code
    assert "except ConnectionError:" in l2_code
    # Internal body computation should be collapsed
    assert "compute_heavy_hash(item)" not in l2_code


def test_fallback_extraction_for_non_python() -> None:
    """Verify regex-based fallback skeleton extraction for typescript or partial snippets."""
    ts_code = """
export class SessionManager {
  private activeCount: number = 0;

  constructor(public readonly id: string) {}

  public async startSession(timeoutMs: number): Promise<boolean> {
    if (timeoutMs <= 0) {
      throw new Error("Invalid timeout");
    }
    const token = generateCryptoToken();
    return true;
  }
}
"""
    l1_fallback = CodeSkeletonExtractor.extract_skeleton(
        source_code=ts_code,
        level=CodeAbstractionLevel.L1_SIGNATURES,
        language="typescript",
    )
    assert "export class SessionManager" in l1_fallback
    assert "public async startSession(timeoutMs: number): Promise<boolean>" in l1_fallback
    assert "generateCryptoToken()" not in l1_fallback


def test_1000_line_code_adaptive_compaction_under_500_token_budget() -> None:
    """Verify injecting 1000 lines of codebase memory adapts within 500 token budget."""
    # Synthesize ~1000 lines of python code across multiple classes and functions
    class_blocks: list[str] = []
    for i in range(25):
        methods: list[str] = []
        for m in range(4):
            methods.append(
                f"""    def process_node_{m}(self, node_id: str, depth: int = 0) -> list[str]:
        \"\"\"Worker {m} logic for graph traversal.\"\"\"
        if depth > 10:
            raise RecursionError("Depth exceeded limit")
        results = []
        for idx in range(100):
            item_hash = f"hash_{{idx}}_{{node_id}}"
            results.append(item_hash)
        return results
"""
            )
        class_code = f"""class ServiceWorkerGroup{i}:
    \"\"\"Service worker group cluster definition {i}.\"\"\"
    cluster_id: str = "cluster_{i}"
    max_workers: int = {i * 2 + 1}

""" + "\n".join(methods)
        class_blocks.append(class_code)

    big_source_code = "\n\n".join(class_blocks)
    line_count = len(big_source_code.splitlines())
    assert line_count >= 800  # Substantial large-scale code block

    items = [
        CodeBlockItem(
            file_path="src/workers/cluster_main.py",
            source_code=big_source_code,
            relevance_score=0.95,
            language="python",
        ),
    ]

    compactor = CodeMemoryBudgetCompactor()
    config = CompactionConfig(
        token_budget=500,
        tokens_per_char_ratio=0.26,
    )
    result = compactor.compact(items=items, config=config)

    assert result.total_original_tokens > 2000
    assert result.total_compacted_tokens <= 500
    assert result.compression_ratio > 0.70
    assert len(result.compacted_blocks) == 1
    compacted = result.compacted_blocks[0]
    assert compacted.abstraction_level in (
        CodeAbstractionLevel.L1_SIGNATURES,
        CodeAbstractionLevel.L2_CONTROL_FLOW,
    )
    assert "class ServiceWorkerGroup" in compacted.content


def test_multi_file_adaptive_downgrade_prioritization() -> None:
    """Verify high-relevance items get higher fidelity than peripheral dependencies."""
    focus_file = """
def main_entry(query: str) -> dict[str, str]:
    \"\"\"Main business execution entry.\"\"\"
    if not query:
        return {}
    return {"status": "ok", "query": query}
"""
    dep1 = """
class HelperA:
    def format_text(self, s: str) -> str:
        res = s.strip()
        for ch in "!@#":
            res = res.replace(ch, "")
        return res
"""
    dep2 = """
class HelperB:
    def log_metric(self, key: str, val: float) -> None:
        payload = {"k": key, "v": val}
        send_socket(payload)
"""
    items = [
        CodeBlockItem(file_path="main.py", source_code=focus_file, relevance_score=0.95),
        CodeBlockItem(file_path="helpers/a.py", source_code=dep1, relevance_score=0.6),
        CodeBlockItem(file_path="helpers/b.py", source_code=dep2, relevance_score=0.3),
    ]

    compactor = CodeMemoryBudgetCompactor()
    # Provide moderate budget that allows main to stay at L3 or L2, but forces dep1/dep2 to L1
    config = CompactionConfig(token_budget=85, tokens_per_char_ratio=0.26)
    result = compactor.compact(items=items, config=config)

    assert result.total_compacted_tokens <= 85
    # Find main block
    main_block = next(b for b in result.compacted_blocks if b.file_path == "main.py")
    dep2_block = next(b for b in result.compacted_blocks if b.file_path == "helpers/b.py")

    assert main_block.abstraction_level in (
        CodeAbstractionLevel.L3_FULL_SOURCE,
        CodeAbstractionLevel.L2_CONTROL_FLOW,
    )
    assert dep2_block.abstraction_level == CodeAbstractionLevel.L1_SIGNATURES
