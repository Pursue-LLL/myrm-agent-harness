# [POS] myrm_agent_harness/toolkits/memory/budget_curator/atomic_curator.py
# [INPUT] AtomicBatchResult, ManagedMemoryItem, MemoryBatchOperation, MemoryBudgetSpec, MemoryOperationType from .types, MemoryBudgetMeter from .budget_meter
# [OUTPUT] AtomicOperationsCurator (原子批量腾挪策展操作符与防混淆事务门禁)

"""原子批量腾挪策展操作符与防混淆事务门禁，杜绝半成功坏账与子串匹配误删。"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.budget_curator.budget_meter import (
    MemoryBudgetMeter,
)
from myrm_agent_harness.toolkits.memory.budget_curator.types import (
    AtomicBatchResult,
    ManagedMemoryItem,
    MemoryBatchOperation,
    MemoryBudgetSpec,
    MemoryOperationType,
)


class AtomicOperationsCurator:
    """原子批量记忆策展操作器，全成或全败事务保证。"""

    def __init__(
        self,
        meter: MemoryBudgetMeter | None = None,
        spec: MemoryBudgetSpec | None = None,
    ) -> None:
        self.meter = meter or MemoryBudgetMeter(spec=spec)

    def _find_item_by_substring(
        self, items: list[ManagedMemoryItem], substring: str
    ) -> tuple[ManagedMemoryItem | None, list[str]]:
        """按子串查找条目，若命中多条返回全部候选 ID 以杜绝误删。"""
        sub_lower = substring.lower()
        matched = [it for it in items if sub_lower in it.content.lower()]
        if len(matched) == 1:
            return matched[0], []
        if len(matched) > 1:
            return None, [m.item_id for m in matched]
        return None, []

    def apply_operations(
        self,
        current_items: list[ManagedMemoryItem],
        operations: list[MemoryBatchOperation],
    ) -> AtomicBatchResult:
        """原子执行批量记忆腾挪操作（全成功或全回滚）。"""
        initial_budget = self.meter.evaluate_budget(current_items)
        if not operations:
            return AtomicBatchResult(
                is_success=True,
                applied_count=0,
                rolled_back=False,
                error_message="",
                current_budget=initial_budget,
                retained_items=list(current_items),
            )

        simulated = list(current_items)

        # 1. 模拟执行全部操作
        for idx, op in enumerate(operations, start=1):
            if op.operation_type == MemoryOperationType.REMOVE:
                target_item: ManagedMemoryItem | None = None
                if op.target_id:
                    for it in simulated:
                        if it.item_id == op.target_id:
                            target_item = it
                            break
                    if not target_item:
                        return AtomicBatchResult(
                            is_success=False,
                            applied_count=0,
                            rolled_back=True,
                            error_message=f"Op #{idx} (REMOVE) failed: item_id '{op.target_id}' not found",
                            current_budget=initial_budget,
                            retained_items=list(current_items),
                        )
                elif op.target_substring:
                    found, candidates = self._find_item_by_substring(
                        simulated, op.target_substring
                    )
                    if candidates:
                        return AtomicBatchResult(
                            is_success=False,
                            applied_count=0,
                            rolled_back=True,
                            error_message=(
                                f"Op #{idx} (REMOVE) collision: substring '{op.target_substring}' "
                                f"matched multiple candidates {candidates}. Specify explicit target_id"
                            ),
                            current_budget=initial_budget,
                            retained_items=list(current_items),
                        )
                    if not found:
                        return AtomicBatchResult(
                            is_success=False,
                            applied_count=0,
                            rolled_back=True,
                            error_message=f"Op #{idx} (REMOVE) failed: substring '{op.target_substring}' not found",
                            current_budget=initial_budget,
                            retained_items=list(current_items),
                        )
                    target_item = found
                else:
                    return AtomicBatchResult(
                        is_success=False,
                        applied_count=0,
                        rolled_back=True,
                        error_message=f"Op #{idx} (REMOVE) missing target_id or target_substring",
                        current_budget=initial_budget,
                        retained_items=list(current_items),
                    )

                simulated = [it for it in simulated if it.item_id != target_item.item_id]

            elif op.operation_type == MemoryOperationType.ADD:
                if not op.new_id or not op.new_content:
                    return AtomicBatchResult(
                        is_success=False,
                        applied_count=0,
                        rolled_back=True,
                        error_message=f"Op #{idx} (ADD) missing new_id or new_content",
                        current_budget=initial_budget,
                        retained_items=list(current_items),
                    )
                # 检查 ID 冲突
                if any(it.item_id == op.new_id for it in simulated):
                    return AtomicBatchResult(
                        is_success=False,
                        applied_count=0,
                        rolled_back=True,
                        error_message=f"Op #{idx} (ADD) conflict: item_id '{op.new_id}' already exists",
                        current_budget=initial_budget,
                        retained_items=list(current_items),
                    )
                tokens = (
                    op.estimated_tokens
                    if op.estimated_tokens > 0
                    else self.meter.estimate_tokens(op.new_content)
                )
                simulated.append(
                    ManagedMemoryItem(
                        item_id=op.new_id,
                        content=op.new_content,
                        token_count=tokens,
                    )
                )

            elif op.operation_type == MemoryOperationType.REPLACE:
                target_id = op.target_id
                if not target_id and op.target_substring:
                    found, candidates = self._find_item_by_substring(
                        simulated, op.target_substring
                    )
                    if candidates:
                        return AtomicBatchResult(
                            is_success=False,
                            applied_count=0,
                            rolled_back=True,
                            error_message=(
                                f"Op #{idx} (REPLACE) collision: substring '{op.target_substring}' "
                                f"matched multiple candidates {candidates}"
                            ),
                            current_budget=initial_budget,
                            retained_items=list(current_items),
                        )
                    if not found:
                        return AtomicBatchResult(
                            is_success=False,
                            applied_count=0,
                            rolled_back=True,
                            error_message=f"Op #{idx} (REPLACE) failed: substring '{op.target_substring}' not found",
                            current_budget=initial_budget,
                            retained_items=list(current_items),
                        )
                    target_id = found.item_id

                if not target_id or not op.new_content:
                    return AtomicBatchResult(
                        is_success=False,
                        applied_count=0,
                        rolled_back=True,
                        error_message=f"Op #{idx} (REPLACE) missing target or new_content",
                        current_budget=initial_budget,
                        retained_items=list(current_items),
                    )

                replaced = False
                new_simulated: list[ManagedMemoryItem] = []
                for it in simulated:
                    if it.item_id == target_id:
                        new_id = op.new_id or target_id
                        tokens = (
                            op.estimated_tokens
                            if op.estimated_tokens > 0
                            else self.meter.estimate_tokens(op.new_content)
                        )
                        new_simulated.append(
                            ManagedMemoryItem(
                                item_id=new_id,
                                content=op.new_content,
                                token_count=tokens,
                            )
                        )
                        replaced = True
                    else:
                        new_simulated.append(it)

                if not replaced:
                    return AtomicBatchResult(
                        is_success=False,
                        applied_count=0,
                        rolled_back=True,
                        error_message=f"Op #{idx} (REPLACE) failed: target_id '{target_id}' not found",
                        current_budget=initial_budget,
                        retained_items=list(current_items),
                    )
                simulated = new_simulated

        # 2. 事务完成后整体预算校验
        new_budget = self.meter.evaluate_budget(simulated)
        if new_budget.is_overflow:
            return AtomicBatchResult(
                is_success=False,
                applied_count=0,
                rolled_back=True,
                error_message=(
                    f"Atomic batch rejected: memory budget overflowed [Used: {new_budget.used_tokens}/"
                    f"{new_budget.max_tokens} tokens ({new_budget.token_usage_pct}%), "
                    f"Slots: {new_budget.used_slots}/{new_budget.max_slots}]. "
                    f"Please combine removals with additions."
                ),
                current_budget=initial_budget,
                retained_items=list(current_items),
            )

        # 3. 提交成功
        return AtomicBatchResult(
            is_success=True,
            applied_count=len(operations),
            rolled_back=False,
            error_message="",
            current_budget=new_budget,
            retained_items=simulated,
        )
