"""MemoryManager mixin for token-budget-aware code memory compaction.

[INPUT]
- toolkits.memory.compaction.budget_compactor::CodeMemoryBudgetCompactor (POS: token-budget-aware compactor)
- toolkits.memory.compaction.types::CodeBlockItem, CompactedBlock, CompactionConfig, CompactionResult (POS: compaction contracts)

[OUTPUT]
- MemoryManagerCodeCompactionMixin: runtime orchestration methods for code memory compaction

[POS]
Partial mixin for MemoryManager providing code snippet compaction against context token budgets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.compaction.budget_compactor import (
        CodeMemoryBudgetCompactor,
    )
    from myrm_agent_harness.toolkits.memory.compaction.types import (
        CodeBlockItem,
        CompactedBlock,
        CompactionResult,
    )


class MemoryManagerCodeCompactionMixin:
    """Provides methods for compacting codebase semantic memories to fit token budgets."""

    def compact_code_memory_item(
        self,
        source_code: str,
        *,
        file_path: str = "main.py",
        token_budget: int = 500,
        relevance_score: float = 1.0,
        compactor: CodeMemoryBudgetCompactor | None = None,
    ) -> CompactedBlock | None:
        """Compact a single code snippet into hierarchical abstraction levels (L1/L2/L3) fitting the token budget."""
        from myrm_agent_harness.toolkits.memory.compaction.budget_compactor import (
            CodeMemoryBudgetCompactor,
        )
        from myrm_agent_harness.toolkits.memory.compaction.types import (
            CodeBlockItem,
            CompactionConfig,
        )

        active_compactor = compactor or CodeMemoryBudgetCompactor()
        item = CodeBlockItem(
            file_path=file_path,
            source_code=source_code,
            relevance_score=relevance_score,
        )
        config = CompactionConfig(token_budget=token_budget)
        result = active_compactor.compact([item], config=config)
        return result.compacted_blocks[0] if result.compacted_blocks else None

    def compact_code_memory_batch(
        self,
        items: list[CodeBlockItem],
        *,
        token_budget: int = 2000,
        compactor: CodeMemoryBudgetCompactor | None = None,
    ) -> CompactionResult:
        """Compact a collection of code snippets, prioritizing higher relevance items while respecting overall budget."""
        from myrm_agent_harness.toolkits.memory.compaction.budget_compactor import (
            CodeMemoryBudgetCompactor,
        )
        from myrm_agent_harness.toolkits.memory.compaction.types import (
            CompactionConfig,
        )

        active_compactor = compactor or CodeMemoryBudgetCompactor()
        config = CompactionConfig(token_budget=token_budget)
        return active_compactor.compact(items, config=config)
