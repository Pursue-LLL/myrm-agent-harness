"""Token-budget-aware dynamic compaction engine for codebase semantic memories.

[INPUT]
- toolkits.memory.compaction.ast_skeleton::CodeSkeletonExtractor (POS: AST-based and regex-fallback code
  skeleton extractor for multi-tier compression.)
- toolkits.memory.compaction.types::CodeAbstractionLevel, CodeBlockItem, CompactedBlock, CompactionConfig,
  CompactionResult (POS: Type definitions and contracts for Token-Budget-Aware Code Memory Compaction.)

[OUTPUT]
- CodeMemoryBudgetCompactor: Dynamic multi-tier code memory compactor guided by available token budgets.

[POS]
Token-budget-aware dynamic compaction engine for codebase semantic memories.
"""

from __future__ import annotations

from .ast_skeleton import CodeSkeletonExtractor
from .types import (
    CodeAbstractionLevel,
    CodeBlockItem,
    CompactedBlock,
    CompactionConfig,
    CompactionResult,
)


class CodeMemoryBudgetCompactor:
    """Dynamic multi-tier code memory compactor guided by available token budgets."""

    def __init__(self, default_config: CompactionConfig | None = None) -> None:
        self._default_config = default_config or CompactionConfig()

    def compact(
        self,
        items: list[CodeBlockItem],
        config: CompactionConfig | None = None,
    ) -> CompactionResult:
        """Compact a collection of code blocks to fit strictly within the token budget."""
        cfg = config or self._default_config
        if not items:
            return CompactionResult(
                compacted_blocks=[],
                total_original_tokens=0,
                total_compacted_tokens=0,
                budget_limit=cfg.token_budget,
                compression_ratio=0.0,
            )

        # 1. Compute original token estimations
        orig_tokens: list[int] = [
            CodeSkeletonExtractor.estimate_tokens(item.source_code, cfg.tokens_per_char_ratio)
            for item in items
        ]
        total_orig_tokens = sum(orig_tokens)

        # If already within budget, keep everything at L3_FULL_SOURCE
        if total_orig_tokens <= cfg.token_budget:
            blocks = [
                CompactedBlock(
                    file_path=item.file_path,
                    abstraction_level=CodeAbstractionLevel.L3_FULL_SOURCE,
                    content=item.source_code,
                    original_token_count=tokens,
                    compacted_token_count=tokens,
                )
                for item, tokens in zip(items, orig_tokens, strict=True)
            ]
            return CompactionResult(
                compacted_blocks=blocks,
                total_original_tokens=total_orig_tokens,
                total_compacted_tokens=total_orig_tokens,
                budget_limit=cfg.token_budget,
                compression_ratio=0.0,
            )

        # 2. Sort indices by relevance score descending
        sorted_indices = sorted(
            range(len(items)),
            key=lambda idx: items[idx].relevance_score,
            reverse=True,
        )

        # 3. Progressive tier assignment search
        # Attempt assignments from highest fidelity to lowest fidelity
        assigned_levels: dict[int, CodeAbstractionLevel] = {}
        use_strip_private = cfg.strip_private_symbols

        # Tier strategy 1: Top focus items at L3, peripheral at L2
        top_focus_idx = sorted_indices[0] if sorted_indices else -1
        for idx in sorted_indices:
            if idx == top_focus_idx and items[idx].relevance_score >= 0.8:
                assigned_levels[idx] = CodeAbstractionLevel.L3_FULL_SOURCE
            else:
                assigned_levels[idx] = CodeAbstractionLevel.L2_CONTROL_FLOW

        candidates = self._render_blocks(items, orig_tokens, assigned_levels, use_strip_private, cfg)
        current_tokens = sum(b.compacted_token_count for b in candidates)

        # Tier strategy 2: If over budget, downgrade peripheral from L2 to L1
        if current_tokens > cfg.token_budget:
            for idx in reversed(sorted_indices):
                if idx != top_focus_idx:
                    assigned_levels[idx] = CodeAbstractionLevel.L1_SIGNATURES
                    candidates = self._render_blocks(
                        items, orig_tokens, assigned_levels, use_strip_private, cfg
                    )
                    current_tokens = sum(b.compacted_token_count for b in candidates)
                    if current_tokens <= cfg.token_budget:
                        break

        # Tier strategy 3: If still over budget, downgrade top focus from L3 to L2, then L1
        if current_tokens > cfg.token_budget and top_focus_idx >= 0:
            assigned_levels[top_focus_idx] = CodeAbstractionLevel.L2_CONTROL_FLOW
            candidates = self._render_blocks(
                items, orig_tokens, assigned_levels, use_strip_private, cfg
            )
            current_tokens = sum(b.compacted_token_count for b in candidates)

            if current_tokens > cfg.token_budget:
                assigned_levels[top_focus_idx] = CodeAbstractionLevel.L1_SIGNATURES
                candidates = self._render_blocks(
                    items, orig_tokens, assigned_levels, use_strip_private, cfg
                )
                current_tokens = sum(b.compacted_token_count for b in candidates)

        # Tier strategy 4: If all at L1 and still over budget, enforce strip_private_symbols
        if current_tokens > cfg.token_budget and not use_strip_private:
            use_strip_private = True
            candidates = self._render_blocks(
                items, orig_tokens, assigned_levels, use_strip_private, cfg
            )
            current_tokens = sum(b.compacted_token_count for b in candidates)

        # Tier strategy 5: Strict emergency budget clamp ensuring total_tokens <= token_budget
        if current_tokens > cfg.token_budget:
            candidates = self._emergency_clamp(
                candidates, cfg.token_budget, cfg.tokens_per_char_ratio
            )
            current_tokens = sum(b.compacted_token_count for b in candidates)

        comp_ratio = max(0.0, 1.0 - (float(current_tokens) / max(1, total_orig_tokens)))

        return CompactionResult(
            compacted_blocks=candidates,
            total_original_tokens=total_orig_tokens,
            total_compacted_tokens=current_tokens,
            budget_limit=cfg.token_budget,
            compression_ratio=round(comp_ratio, 4),
        )

    def _render_blocks(
        self,
        items: list[CodeBlockItem],
        orig_tokens: list[int],
        levels: dict[int, CodeAbstractionLevel],
        strip_private: bool,
        config: CompactionConfig,
    ) -> list[CompactedBlock]:
        """Render all blocks at their assigned abstraction levels."""
        rendered: list[CompactedBlock] = []
        for idx, item in enumerate(items):
            lvl = levels.get(idx, CodeAbstractionLevel.L1_SIGNATURES)
            compacted_code = CodeSkeletonExtractor.extract_skeleton(
                source_code=item.source_code,
                level=lvl,
                strip_private=strip_private,
                language=item.language,
            )
            tok = CodeSkeletonExtractor.estimate_tokens(compacted_code, config.tokens_per_char_ratio)
            rendered.append(
                CompactedBlock(
                    file_path=item.file_path,
                    abstraction_level=lvl,
                    content=compacted_code,
                    original_token_count=orig_tokens[idx],
                    compacted_token_count=tok,
                )
            )
        return rendered

    def _emergency_clamp(
        self,
        blocks: list[CompactedBlock],
        token_budget: int,
        ratio: float,
    ) -> list[CompactedBlock]:
        """Emergency budget enforcement by trimming content from lowest priority items."""
        total = sum(b.compacted_token_count for b in blocks)
        if total <= token_budget:
            return blocks

        clamped: list[CompactedBlock] = []
        budget_remaining = token_budget

        for block in blocks:
            if block.compacted_token_count <= budget_remaining:
                clamped.append(block)
                budget_remaining -= block.compacted_token_count
            elif budget_remaining > 0:
                notice = "\n# ... [TRUNCATED]"
                notice_tokens = CodeSkeletonExtractor.estimate_tokens(notice, ratio)
                avail_tokens = max(1, budget_remaining - notice_tokens)
                max_chars = max(10, int(avail_tokens / max(0.05, ratio)))
                truncated_content = block.content[:max_chars] + notice
                new_tok = CodeSkeletonExtractor.estimate_tokens(truncated_content, ratio)

                while new_tok > budget_remaining and len(truncated_content) > len(notice) + 5:
                    max_chars = max(1, max_chars - 5)
                    truncated_content = block.content[:max_chars] + notice
                    new_tok = CodeSkeletonExtractor.estimate_tokens(truncated_content, ratio)

                if new_tok <= budget_remaining:
                    clamped.append(
                        CompactedBlock(
                            file_path=block.file_path,
                            abstraction_level=block.abstraction_level,
                            content=truncated_content,
                            original_token_count=block.original_token_count,
                            compacted_token_count=new_tok,
                        )
                    )
                    budget_remaining -= new_tok
                else:
                    clamped.append(
                        CompactedBlock(
                            file_path=block.file_path,
                            abstraction_level=block.abstraction_level,
                            content="",
                            original_token_count=block.original_token_count,
                            compacted_token_count=0,
                        )
                    )
            else:
                clamped.append(
                    CompactedBlock(
                        file_path=block.file_path,
                        abstraction_level=block.abstraction_level,
                        content="",
                        original_token_count=block.original_token_count,
                        compacted_token_count=0,
                    )
                )
        return clamped

