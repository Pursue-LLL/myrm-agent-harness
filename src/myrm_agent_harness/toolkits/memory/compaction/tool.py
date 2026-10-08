"""Agent-facing LangChain tool for token-budget-aware code memory compaction.

[INPUT]
- toolkits.memory.compaction.budget_compactor::CodeMemoryBudgetCompactor
- toolkits.memory.compaction.types::CodeAbstractionLevel, CodeBlockItem, CompactionConfig

[OUTPUT]
- CompactCodeMemoryInput: Pydantic input schema for tool
- create_code_memory_compaction_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool for token-budget-aware code memory compaction.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.compaction.budget_compactor import (
    CodeMemoryBudgetCompactor,
)
from myrm_agent_harness.toolkits.memory.compaction.types import (
    CodeBlockItem,
    CompactionConfig,
)


class CompactCodeMemoryInput(BaseModel):
    """Input schema for token-budget-aware code memory compaction."""

    source_code: str = Field(
        description="Source code content or code snippet from repository to be compacted"
    )
    file_path: str = Field(
        default="main.py",
        description="Optional file path or filename to infer syntax and language parser",
    )
    token_budget: int = Field(
        default=500,
        description="Maximum token budget available in the context window for this code memory",
    )
    relevance_score: float = Field(
        default=1.0,
        description="Relevance score of this code snippet (higher score preserves higher detail level)",
    )


def create_code_memory_compaction_tool(
    compactor: CodeMemoryBudgetCompactor | None = None,
) -> BaseTool:
    """Create a LangChain standard tool allowing agents to adaptively compact code memories within token budgets."""
    active_compactor = compactor or CodeMemoryBudgetCompactor()

    @tool("compact_code_memory", args_schema=CompactCodeMemoryInput)
    def compact_code_memory(
        source_code: str,
        file_path: str = "main.py",
        token_budget: int = 500,
        relevance_score: float = 1.0,
    ) -> str:
        """Compact codebase memory snippets into L1 signatures, L2 control flow, or L3 source code fitting token limits."""
        item = CodeBlockItem(
            file_path=file_path,
            source_code=source_code,
            relevance_score=relevance_score,
        )
        config = CompactionConfig(token_budget=token_budget)
        result = active_compactor.compact([item], config=config)

        if not result.compacted_blocks:
            return json.dumps(
                {
                    "file_path": file_path,
                    "abstraction_level": "L1_SIGNATURES",
                    "compacted_code": "",
                    "original_tokens": 0,
                    "compacted_tokens": 0,
                    "tokens_saved": 0,
                    "compression_ratio": 0.0,
                },
                ensure_ascii=False,
            )

        block = result.compacted_blocks[0]
        tokens_saved = max(0, block.original_token_count - block.compacted_token_count)
        compression_ratio = round(
            (tokens_saved / block.original_token_count * 100)
            if block.original_token_count > 0
            else 0.0,
            1,
        )

        output = {
            "file_path": block.file_path,
            "abstraction_level": block.abstraction_level.value,
            "compacted_code": block.content,
            "original_tokens": block.original_token_count,
            "compacted_tokens": block.compacted_token_count,
            "tokens_saved": tokens_saved,
            "compression_ratio": compression_ratio,
        }
        return json.dumps(output, ensure_ascii=False)

    return compact_code_memory
