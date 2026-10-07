# [POS] myrm_agent_harness/agent/context_management/compression_flush/subagent_memory_isolation.py
# [INPUT] EphemeralMemoryOverlaySpec, FlushItem, MemoryIsolationScope, SubagentMemoryPolicy from .types
# [OUTPUT] SubagentMemoryIsolationController (子智能体内存沙箱隔离控制器与临时覆盖卷)

"""子智能体轻量内存沙箱隔离控制器与临时覆盖卷管理。

提供父级只读记忆快照、子 Agent 运行期独立 Ephemeral 临时写入卷，
以及任务完成后的核心成果选择性合流与无痕销毁机制，彻底杜绝跨上下文记忆污染。
"""

from __future__ import annotations

import threading

from myrm_agent_harness.agent.context_management.compression_flush.types import (
    EphemeralMemoryOverlaySpec,
    FlushItem,
    MemoryIsolationScope,
    SubagentMemoryPolicy,
)


class SubagentMemoryIsolationController:
    """子智能体轻量内存沙箱与临时覆盖卷生命周期控制器。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # overlay_id -> EphemeralMemoryOverlaySpec
        self._specs: dict[str, EphemeralMemoryOverlaySpec] = {}
        # overlay_id -> SubagentMemoryPolicy
        self._policies: dict[str, SubagentMemoryPolicy] = {}
        # overlay_id -> list of parent snapshot FlushItems (只读)
        self._parent_snapshots: dict[str, list[FlushItem]] = {}
        # overlay_id -> dict[item_id, FlushItem] (过程临时覆盖卷)
        self._ephemeral_overlays: dict[str, dict[str, FlushItem]] = {}

    def create_subagent_overlay(
        self,
        spec: EphemeralMemoryOverlaySpec,
        parent_items: list[FlushItem] | None = None,
        policy: SubagentMemoryPolicy | None = None,
    ) -> None:
        """为派生的子智能体初始化独立的内存沙箱与临时覆盖卷。"""
        with self._lock:
            self._specs[spec.overlay_id] = spec
            self._policies[spec.overlay_id] = policy or SubagentMemoryPolicy()
            self._parent_snapshots[spec.overlay_id] = (
                list(parent_items) if parent_items else []
            )
            self._ephemeral_overlays[spec.overlay_id] = {}

    def has_overlay(self, overlay_id: str) -> bool:
        """检查指定子智能体覆盖卷是否存在。"""
        with self._lock:
            return overlay_id in self._specs

    def append_subagent_ephemeral(
        self, overlay_id: str, item: FlushItem
    ) -> bool:
        """子智能体执行期写入临时过程记忆。

        若策略禁止写入或超过容量上限，返回 False。
        """
        with self._lock:
            spec = self._specs.get(overlay_id)
            policy = self._policies.get(overlay_id)
            if not spec or not policy:
                return False

            if not policy.allow_ephemeral_write:
                return False

            overlay_dict = self._ephemeral_overlays[overlay_id]
            if len(overlay_dict) >= spec.max_overlay_items:
                return False

            overlay_dict[item.item_id] = item
            return True

    def get_subagent_view(self, overlay_id: str) -> list[FlushItem]:
        """获取子智能体视角的合成记忆列表。

        由父级只读快照（若策略允许）与子级过程覆盖卷按 item_id 合成，子级优先。
        """
        with self._lock:
            spec = self._specs.get(overlay_id)
            policy = self._policies.get(overlay_id)
            if not spec or not policy:
                return []

            merged: dict[str, FlushItem] = {}

            if (
                policy.allow_profile_read
                and policy.isolation_scope != MemoryIsolationScope.STATELESS_CRON
            ):
                for p_item in self._parent_snapshots.get(overlay_id, []):
                    merged[p_item.item_id] = p_item

            # 子级覆盖卷覆盖父级同 ID 项
            for sub_item in self._ephemeral_overlays.get(
                overlay_id, {}
            ).values():
                merged[sub_item.item_id] = sub_item

            return list(merged.values())

    def get_overlay_ephemeral_items(self, overlay_id: str) -> list[FlushItem]:
        """仅提取子智能体内部产生的过程临时项列表。"""
        with self._lock:
            return list(self._ephemeral_overlays.get(overlay_id, {}).values())

    def merge_selective_to_parent(
        self, overlay_id: str, selected_item_ids: list[str]
    ) -> list[FlushItem]:
        """任务完成后，仅提取指定核心成果准备合并回父级，并根据策略自动清理。"""
        with self._lock:
            spec = self._specs.get(overlay_id)
            if not spec or not spec.allow_selective_merge:
                return []

            ephemeral = self._ephemeral_overlays.get(overlay_id, {})
            harvested: list[FlushItem] = []
            for target_id in selected_item_ids:
                if target_id in ephemeral:
                    harvested.append(ephemeral[target_id])

            if spec.auto_purge_on_finish:
                self._purge_internal(overlay_id)

            return harvested

    def purge_overlay(self, overlay_id: str) -> None:
        """手动无痕销毁子智能体的内存沙箱与临时覆盖卷。"""
        with self._lock:
            self._purge_internal(overlay_id)

    def _purge_internal(self, overlay_id: str) -> None:
        """内部无锁销毁方法。"""
        self._specs.pop(overlay_id, None)
        self._policies.pop(overlay_id, None)
        self._parent_snapshots.pop(overlay_id, None)
        self._ephemeral_overlays.pop(overlay_id, None)
