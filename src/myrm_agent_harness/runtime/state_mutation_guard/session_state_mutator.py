"""会话状态并发变异隔离与乐观并发仲裁合并模块.

本模块实现 Copy-on-Write 机制与版本化状态隔离，防止多并发协程直接修改同一全局字典
引发竞态覆写与迭代大小变更崩溃（RuntimeError: dictionary changed size during iteration）。

[INPUT]
- __future__
- copy
- logging
- threading
- time
- uuid

[OUTPUT]
- logger
- IsolatedBranchView
- SessionStateMutator

[POS]
会话状态并发变异隔离与乐观并发仲裁合并模块.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import uuid

from myrm_agent_harness.runtime.state_mutation_guard.mutation_guard_types import (
    PatchCommitResult,
    PatchConflictError,
    PatchConflictStrategy,
    SessionStateSnapshot,
    StateMutationPatch,
)

logger = logging.getLogger(__name__)


class IsolatedBranchView:
    """并发分支专用的独立上下文快照视图.

    分支协程仅在其专属副本上执行读写操作，杜绝跨协程共享字典直接原地修改。
    修改完成后导出 StateMutationPatch 供主线程/权威仲裁器合并。
    """

    def __init__(
        self,
        branch_id: str,
        base_version: int,
        initial_data: dict[str, object],
    ) -> None:
        self.branch_id: str = branch_id
        self.base_version: int = base_version
        self._local_data: dict[str, object] = copy.deepcopy(initial_data)
        self._dirty_keys: set[str] = set()

    def get(self, key: str, default: object = None) -> object:
        """从本地隔离视图读取状态."""
        return self._local_data.get(key, default)

    def set(self, key: str, value: object) -> None:
        """向本地隔离视图写入状态，标记脏键."""
        self._local_data[key] = value
        self._dirty_keys.add(key)

    def delete(self, key: str) -> None:
        """从本地隔离视图中删除键，将其置为特定墓碑或从局部字典移除."""
        if key in self._local_data:
            del self._local_data[key]
            self._dirty_keys.add(key)

    def export_patch(self) -> StateMutationPatch:
        """导出当前分支自创建以来的原子变更包."""
        mutations: dict[str, object] = {
            k: self._local_data[k] for k in self._dirty_keys if k in self._local_data
        }
        return StateMutationPatch(
            patch_id=f"patch_{uuid.uuid4().hex[:8]}",
            branch_id=self.branch_id,
            base_version=self.base_version,
            mutations=mutations,
        )


class SessionStateMutator:
    """权威会话状态管理与无锁冲突仲裁合并引擎.

    采用乐观并发控制（OCC）与不可变快照升级模型。所有变更必须通过 commit_patch 接入。
    """

    def __init__(self, session_id: str, initial_data: dict[str, object] | None = None) -> None:
        self.session_id: str = session_id
        self._version: int = 1
        self._data: dict[str, object] = copy.deepcopy(initial_data) if initial_data else {}
        self._lock: threading.Lock = threading.Lock()
        # 记录每个版本变更的 keys: version -> set[key]
        self._version_history: dict[int, set[str]] = {}
        self._last_updated_at_ms: float = time.time() * 1000

    @property
    def current_version(self) -> int:
        """获取当前权威状态的版本号."""
        with self._lock:
            return self._version

    def create_isolated_view(self, branch_id: str) -> IsolatedBranchView:
        """为并发子分支创建隔离快照视图."""
        with self._lock:
            return IsolatedBranchView(
                branch_id=branch_id,
                base_version=self._version,
                initial_data=self._data,
            )

    def commit_patch(
        self,
        patch: StateMutationPatch,
        strategy: PatchConflictStrategy = PatchConflictStrategy.LAST_WRITE_WINS,
    ) -> PatchCommitResult:
        """将分支的变更 Patch 仲裁合入权威状态.

        依据 base_version 校验并发冲突，并根据指定策略执行合入或拒绝。
        """
        with self._lock:
            conflicted_keys: list[str] = []
            patch_keys = set(patch.mutations.keys())

            # 检查自 base_version 以来是否有其他提交修改了相同的键
            if patch.base_version < self._version:
                for v in range(patch.base_version + 1, self._version + 1):
                    prior_keys = self._version_history.get(v, set())
                    overlap = patch_keys.intersection(prior_keys)
                    for k in overlap:
                        if k not in conflicted_keys:
                            conflicted_keys.append(k)

            # 若发生冲突且策略为严格拒绝
            if conflicted_keys and strategy == PatchConflictStrategy.FAIL_ON_CONFLICT:
                msg = (
                    f"Session state conflict detected in session '{self.session_id}' "
                    f"for branch '{patch.branch_id}'. Conflicting keys: {conflicted_keys}"
                )
                logger.warning(msg)
                raise PatchConflictError(message=msg, conflict_keys=conflicted_keys)

            # 执行合入
            applied_keys: list[str] = []
            for k, val in patch.mutations.items():
                if strategy == PatchConflictStrategy.MERGE_DICT and isinstance(val, dict):
                    existing_val = self._data.get(k)
                    if isinstance(existing_val, dict):
                        merged_dict: dict[str, object] = copy.deepcopy(existing_val)
                        merged_dict.update(val)
                        self._data[k] = merged_dict
                    else:
                        self._data[k] = copy.deepcopy(val)
                else:
                    self._data[k] = copy.deepcopy(val)
                applied_keys.append(k)

            # 递增版本号并记录变更历史
            self._version += 1
            self._version_history[self._version] = set(applied_keys)
            self._last_updated_at_ms = time.time() * 1000

            # 限制历史追溯记录大小，防止无界增长
            if len(self._version_history) > 100:
                oldest_ver = min(self._version_history.keys())
                del self._version_history[oldest_ver]

            return PatchCommitResult(
                success=True,
                resulting_version=self._version,
                applied_keys=applied_keys,
                conflicted_keys=conflicted_keys,
            )

    def get_snapshot(self) -> SessionStateSnapshot:
        """获取当前权威状态的不可变快照."""
        with self._lock:
            return SessionStateSnapshot(
                session_id=self.session_id,
                version=self._version,
                data=copy.deepcopy(self._data),
                updated_at_ms=self._last_updated_at_ms,
            )
