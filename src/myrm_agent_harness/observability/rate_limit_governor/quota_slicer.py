"""
[INPUT]: Workspace IDs, subagent IDs, total available TPM quotas, and concurrency counts.
[OUTPUT]: SubagentQuotaSlice allocations preventing greedy subagents from exhausting team quotas.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/rate_limit_governor/quota_slicer.py
"""

import threading
from typing import Dict, List, Optional, Tuple

from .models import SubagentQuotaSlice


class SubagentQuotaSlicer:
    """
    Allocates and monitors isolated TPM slices across concurrent subagents
    within workspaces, preventing single greedy tasks from disrupting sibling pipelines.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Key: (workspace_id, subagent_id) -> SubagentQuotaSlice
        self._slices: Dict[Tuple[str, str], SubagentQuotaSlice] = {}

    def allocate_slice(
        self,
        workspace_id: str,
        subagent_id: str,
        total_available_tpm: int,
        concurrency_count: int,
    ) -> SubagentQuotaSlice:
        with self._lock:
            key = (workspace_id, subagent_id)
            share = max(1000, total_available_tpm // max(1, concurrency_count))
            slice_entry = SubagentQuotaSlice(
                workspace_id=workspace_id,
                subagent_id=subagent_id,
                allocated_tpm_share=share,
                consumed_tokens_in_window=0,
                remaining_tokens_in_window=share,
                is_throttled=False,
            )
            self._slices[key] = slice_entry
            return slice_entry

    def record_consumption(
        self,
        workspace_id: str,
        subagent_id: str,
        tokens: int,
    ) -> SubagentQuotaSlice:
        with self._lock:
            key = (workspace_id, subagent_id)
            prev = self._slices.get(key)
            if not prev:
                # Default auto-allocated fallback slice
                prev = SubagentQuotaSlice(
                    workspace_id=workspace_id,
                    subagent_id=subagent_id,
                    allocated_tpm_share=20_000,
                    consumed_tokens_in_window=0,
                    remaining_tokens_in_window=20_000,
                    is_throttled=False,
                )

            new_consumed = prev.consumed_tokens_in_window + max(0, tokens)
            new_remaining = max(0, prev.allocated_tpm_share - new_consumed)
            is_throttled = new_consumed >= prev.allocated_tpm_share

            updated = SubagentQuotaSlice(
                workspace_id=workspace_id,
                subagent_id=subagent_id,
                allocated_tpm_share=prev.allocated_tpm_share,
                consumed_tokens_in_window=new_consumed,
                remaining_tokens_in_window=new_remaining,
                is_throttled=is_throttled,
            )
            self._slices[key] = updated
            return updated

    def is_subagent_throttled(self, workspace_id: str, subagent_id: str) -> bool:
        with self._lock:
            slice_entry = self._slices.get((workspace_id, subagent_id))
            return slice_entry.is_throttled if slice_entry else False

    is_throttled = is_subagent_throttled


    def list_slices_for_workspace(self, workspace_id: str) -> List[SubagentQuotaSlice]:
        with self._lock:
            return [s for (ws, _), s in self._slices.items() if ws == workspace_id]

    def reset_window(self, workspace_id: Optional[str] = None) -> None:
        with self._lock:
            for key, prev in list(self._slices.items()):
                if workspace_id is None or key[0] == workspace_id:
                    self._slices[key] = SubagentQuotaSlice(
                        workspace_id=prev.workspace_id,
                        subagent_id=prev.subagent_id,
                        allocated_tpm_share=prev.allocated_tpm_share,
                        consumed_tokens_in_window=0,
                        remaining_tokens_in_window=prev.allocated_tpm_share,
                        is_throttled=False,
                    )
