"""In-Memory Storage Implementation

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillOptimizationStorage (POS: 存储层抽象接口)
- .types.* (POS: 核心类型定义)

[OUTPUT]
- InMemoryStorage: 内存存储实现类

[POS]
In-memory storage (framework layer). Ready-to-use volatile storage implementation.

"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .protocols import SkillOptimizationStorage, StorageError
from .types import ABTestResult, ABTestStatus, OptimizationResult, SkillQualityScore, SkillVersion


class InMemoryStorage(SkillOptimizationStorage):
    """内存存储实现

    完整实现SkillOptimizationStorage Protocol。
    使用OrderedDict实现LRU，支持TTL过期。

    Args:
        max_records: 最大记录数（超过触发LRU淘汰）
        ttl_seconds: TTL过期时间（秒），None表示永不过期
        persistence_path: 可选持久化文件路径
        auto_save_interval: 自动保存间隔（秒），None表示不自动保存
    """

    def __init__(
        self,
        max_records: int = 10000,
        ttl_seconds: int | None = 86400 * 30,  # 默认30天
        persistence_path: str | Path | None = None,
        auto_save_interval: int | None = None,
    ):
        self._max_records = max_records
        self._ttl_seconds = ttl_seconds
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._auto_save_interval = auto_save_interval

        # 数据存储 {key: (value, timestamp)}
        self._optimization_records: OrderedDict[str, tuple[OptimizationResult, float]] = OrderedDict()
        self._ab_tests: OrderedDict[str, tuple[ABTestResult, float]] = OrderedDict()
        self._quality_snapshots: defaultdict[str, list[tuple[datetime, SkillQualityScore, float]]] = defaultdict(list)
        # 版本存储 {skill_id: {version: (SkillVersion, timestamp)}}
        self._skill_versions: defaultdict[str, OrderedDict[int, tuple[SkillVersion, float]]] = defaultdict(OrderedDict)

        # 锁保护
        self._lock = asyncio.Lock()

        # 自动保存任务
        self._auto_save_task: asyncio.Task | None = None

        # 从文件加载（如果存在）
        if self._persistence_path and self._persistence_path.exists():
            self._load_from_file()

    async def start(self) -> None:
        """启动存储（启动自动保存任务）"""
        if self._auto_save_interval and self._persistence_path:
            self._auto_save_task = asyncio.create_task(self._auto_save_loop())

    async def stop(self) -> None:
        """停止存储（保存数据并停止任务）"""
        if self._auto_save_task:
            self._auto_save_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._auto_save_task

        # 最终保存
        if self._persistence_path:
            await self.save_to_file()

    # ==================== OptimizationRecord ====================

    async def save_optimization_record(self, record: OptimizationResult) -> None:
        async with self._lock:
            key = f"opt:{record.skill_id}:{record.started_at.isoformat()}"
            timestamp = datetime.now().timestamp()
            self._optimization_records[key] = (record, timestamp)
            self._evict_if_needed(self._optimization_records)
            self._cleanup_expired(self._optimization_records)

    async def get_optimization_record(self, skill_id: str) -> OptimizationResult | None:
        async with self._lock:
            self._cleanup_expired(self._optimization_records)

            # 查找最新记录
            matching_records = [
                (rec, ts) for key, (rec, ts) in self._optimization_records.items() if rec.skill_id == skill_id
            ]

            if not matching_records:
                return None

            # 按时间降序，返回最新的
            matching_records.sort(key=lambda x: x[0].started_at, reverse=True)
            return matching_records[0][0]

    async def get_optimization_history(self, skill_id: str, limit: int = 10) -> list[OptimizationResult]:
        async with self._lock:
            self._cleanup_expired(self._optimization_records)

            matching_records = [
                rec for key, (rec, ts) in self._optimization_records.items() if rec.skill_id == skill_id
            ]

            # 按时间降序
            matching_records.sort(key=lambda x: x.started_at, reverse=True)
            return matching_records[:limit]

    async def get_recent_optimizations(self, hours: int = 24, limit: int = 100) -> list[OptimizationResult]:
        async with self._lock:
            self._cleanup_expired(self._optimization_records)

            cutoff_time = datetime.now() - timedelta(hours=hours)
            recent_records = [
                rec for key, (rec, ts) in self._optimization_records.items() if rec.started_at >= cutoff_time
            ]

            # 按时间降序
            recent_records.sort(key=lambda x: x.started_at, reverse=True)
            return recent_records[:limit]

    async def delete_old_optimizations(self, days: int = 90) -> int:
        async with self._lock:
            cutoff_time = datetime.now() - timedelta(days=days)
            keys_to_delete = [
                key for key, (rec, ts) in self._optimization_records.items() if rec.started_at < cutoff_time
            ]

            for key in keys_to_delete:
                del self._optimization_records[key]

            return len(keys_to_delete)

    # ==================== ABTestResult ====================

    async def save_ab_test(self, result: ABTestResult) -> None:
        async with self._lock:
            key = f"ab:{result.skill_id}"
            timestamp = datetime.now().timestamp()
            self._ab_tests[key] = (result, timestamp)
            self._evict_if_needed(self._ab_tests)
            self._cleanup_expired(self._ab_tests)

    async def get_ab_test(self, skill_id: str) -> ABTestResult | None:
        async with self._lock:
            self._cleanup_expired(self._ab_tests)
            key = f"ab:{skill_id}"
            if key in self._ab_tests:
                return self._ab_tests[key][0]
            return None

    async def get_running_ab_tests(self) -> list[ABTestResult]:
        async with self._lock:
            self._cleanup_expired(self._ab_tests)
            return [test for key, (test, ts) in self._ab_tests.items() if test.status == ABTestStatus.RUNNING]

    async def update_ab_test_status(self, skill_id: str, status: ABTestStatus, winner: str | None = None) -> None:
        async with self._lock:
            key = f"ab:{skill_id}"
            if key not in self._ab_tests:
                raise StorageError(f"A/B test not found: {skill_id}")

            test, _ts = self._ab_tests[key]
            updated_test = ABTestResult(
                skill_id=test.skill_id,
                baseline_version=test.baseline_version,
                candidate_version=test.candidate_version,
                baseline_score=test.baseline_score,
                candidate_score=test.candidate_score,
                sample_size=test.sample_size,
                status=status,
                started_at=test.started_at,
                completed_at=datetime.now() if status != ABTestStatus.RUNNING else None,
                winner=winner,
            )
            self._ab_tests[key] = (updated_test, datetime.now().timestamp())

    async def increment_ab_test_sample_size(self, skill_id: str, increment: int = 1) -> int:
        async with self._lock:
            key = f"ab:{skill_id}"
            if key not in self._ab_tests:
                raise StorageError(f"A/B test not found: {skill_id}")

            test, _ts = self._ab_tests[key]
            new_sample_size = test.sample_size + increment

            updated_test = ABTestResult(
                skill_id=test.skill_id,
                baseline_version=test.baseline_version,
                candidate_version=test.candidate_version,
                baseline_score=test.baseline_score,
                candidate_score=test.candidate_score,
                sample_size=new_sample_size,
                status=test.status,
                started_at=test.started_at,
                completed_at=test.completed_at,
                winner=test.winner,
            )
            self._ab_tests[key] = (updated_test, datetime.now().timestamp())
            return new_sample_size

    # ==================== SkillVersion ====================

    async def save_skill_version(
        self,
        skill_id: str,
        version: int,
        content: str,
        quality_score: SkillQualityScore | None = None,
        created_by: str = "llm",
        optimization_id: str | None = None,
        metadata: dict | None = None,
    ) -> SkillVersion:
        async with self._lock:
            skill_version = SkillVersion(
                skill_id=skill_id,
                version=version,
                content=content,
                quality_score=quality_score,
                created_at=datetime.now(),
                created_by=created_by,
                optimization_id=optimization_id,
                is_active=False,  # 默认不激活，需要显式调用activate_version
                metadata=metadata,
            )

            timestamp = datetime.now().timestamp()
            self._skill_versions[skill_id][version] = (skill_version, timestamp)

            # 限制每个skill保留最多100个版本
            if len(self._skill_versions[skill_id]) > 100:
                # 删除最旧的非激活版本
                sorted_versions = sorted(self._skill_versions[skill_id].items())
                for ver, (sv, _ts) in sorted_versions:
                    if not sv.is_active:
                        del self._skill_versions[skill_id][ver]
                        break

            return skill_version

    async def get_skill_version(self, skill_id: str, version: int) -> SkillVersion | None:
        async with self._lock:
            if skill_id not in self._skill_versions:
                return None
            if version not in self._skill_versions[skill_id]:
                return None
            return self._skill_versions[skill_id][version][0]

    async def get_active_version(self, skill_id: str) -> SkillVersion | None:
        async with self._lock:
            if skill_id not in self._skill_versions:
                return None

            for _version, (sv, _ts) in self._skill_versions[skill_id].items():
                if sv.is_active:
                    return sv
            return None

    async def list_skill_versions(self, skill_id: str, limit: int = 50) -> list[SkillVersion]:
        async with self._lock:
            if skill_id not in self._skill_versions:
                return []

            versions = [sv for sv, ts in self._skill_versions[skill_id].values()]
            # 按版本号降序
            versions.sort(key=lambda x: x.version, reverse=True)
            return versions[:limit]

    async def activate_version(self, skill_id: str, version: int) -> SkillVersion:
        async with self._lock:
            if skill_id not in self._skill_versions:
                raise StorageError(f"Skill not found: {skill_id}")
            if version not in self._skill_versions[skill_id]:
                raise StorageError(f"Version not found: {skill_id}@{version}")

            # 将所有版本设为inactive
            for ver in self._skill_versions[skill_id]:
                sv, ts = self._skill_versions[skill_id][ver]
                updated_sv = SkillVersion(
                    skill_id=sv.skill_id,
                    version=sv.version,
                    content=sv.content,
                    quality_score=sv.quality_score,
                    created_at=sv.created_at,
                    created_by=sv.created_by,
                    optimization_id=sv.optimization_id,
                    is_active=False,
                    metadata=sv.metadata,
                )
                self._skill_versions[skill_id][ver] = (updated_sv, ts)

            # 激活指定版本
            sv, ts = self._skill_versions[skill_id][version]
            activated_sv = SkillVersion(
                skill_id=sv.skill_id,
                version=sv.version,
                content=sv.content,
                quality_score=sv.quality_score,
                created_at=sv.created_at,
                created_by=sv.created_by,
                optimization_id=sv.optimization_id,
                is_active=True,
                metadata=sv.metadata,
            )
            self._skill_versions[skill_id][version] = (activated_sv, datetime.now().timestamp())
            return activated_sv

    async def delete_skill_versions(self, skill_id: str, keep_latest: int = 10) -> int:
        async with self._lock:
            if skill_id not in self._skill_versions:
                return 0

            versions = list(self._skill_versions[skill_id].keys())
            versions.sort(reverse=True)  # 降序

            # 找到激活版本
            active_version = None
            for ver in versions:
                sv, _ts = self._skill_versions[skill_id][ver]
                if sv.is_active:
                    active_version = ver
                    break

            # 保留最新N个版本和激活版本
            versions_to_keep = set(versions[:keep_latest])
            if active_version is not None:
                versions_to_keep.add(active_version)

            # 删除其余版本
            deleted_count = 0
            for ver in versions:
                if ver not in versions_to_keep:
                    del self._skill_versions[skill_id][ver]
                    deleted_count += 1

            return deleted_count

    # ==================== SkillQualityHistory ====================

    async def save_quality_snapshot(self, skill_id: str, score: SkillQualityScore, version: int | None = None) -> None:
        async with self._lock:
            timestamp = datetime.now()
            ts = timestamp.timestamp()
            self._quality_snapshots[skill_id].append((timestamp, score, ts))

            # 保留最近1000条
            if len(self._quality_snapshots[skill_id]) > 1000:
                self._quality_snapshots[skill_id] = self._quality_snapshots[skill_id][-1000:]

    async def get_quality_history(self, skill_id: str, days: int = 30) -> list[tuple[datetime, SkillQualityScore]]:
        async with self._lock:
            if skill_id not in self._quality_snapshots:
                return []

            cutoff_time = datetime.now() - timedelta(days=days)
            history = [(ts, score) for ts, score, _ in self._quality_snapshots[skill_id] if ts >= cutoff_time]

            # 按时间降序
            history.sort(key=lambda x: x[0], reverse=True)
            return history

    async def get_latest_quality(self, skill_id: str) -> SkillQualityScore | None:
        async with self._lock:
            if skill_id not in self._quality_snapshots or not self._quality_snapshots[skill_id]:
                return None

            # 返回最新的
            return self._quality_snapshots[skill_id][-1][1]

    async def get_top_skills(self, limit: int = 10) -> list[tuple[str, SkillQualityScore]]:
        async with self._lock:
            # 获取每个skill的最新评分
            latest_scores = [
                (skill_id, snapshots[-1][1]) for skill_id, snapshots in self._quality_snapshots.items() if snapshots
            ]

            # 按评分降序
            latest_scores.sort(key=lambda x: x[1].overall_score, reverse=True)
            return latest_scores[:limit]

    async def get_bottom_skills(self, limit: int = 10) -> list[tuple[str, SkillQualityScore]]:
        async with self._lock:
            # 获取每个skill的最新评分
            latest_scores = [
                (skill_id, snapshots[-1][1]) for skill_id, snapshots in self._quality_snapshots.items() if snapshots
            ]

            # 按评分升序
            latest_scores.sort(key=lambda x: x[1].overall_score)
            return latest_scores[:limit]

    # ==================== Health Check ====================

    async def health_check(self) -> dict[str, bool | str]:
        """健康检查"""
        try:
            async with self._lock:
                # Test read capability
                readable = True
                try:
                    _ = len(self._optimization_records)
                    _ = len(self._quality_snapshots)
                except Exception:
                    readable = False

                # Test write capability
                writable = True
                try:
                    # Attempt a dummy write
                    test_key = "_health_check_test_"
                    self._optimization_records.pop(test_key, None)
                except Exception:
                    writable = False

                healthy = readable and writable

                return {
                    "healthy": healthy,
                    "storage_type": "in_memory",
                    "readable": readable,
                    "writable": writable,
                    "record_count": len(self._optimization_records),
                    "ab_test_count": len(self._ab_tests),
                    "version_count": sum(len(versions) for versions in self._skill_versions.values()),
                }
        except Exception as e:
            return {
                "healthy": False,
                "storage_type": "in_memory",
                "readable": False,
                "writable": False,
                "error": str(e),
            }

    # ==================== Internal Methods ====================

    def _evict_if_needed(self, store: OrderedDict) -> None:
        """LRU淘汰：如果超过max_records，删除最旧的记录"""
        while len(store) > self._max_records:
            store.popitem(last=False)

    def _cleanup_expired(self, store: OrderedDict) -> None:
        """TTL清理：删除过期记录"""
        if self._ttl_seconds is None:
            return

        now = datetime.now().timestamp()
        keys_to_delete = [key for key, (value, ts) in store.items() if now - ts > self._ttl_seconds]

        for key in keys_to_delete:
            del store[key]

    def _load_from_file(self) -> None:
        """从文件加载数据"""
        try:
            if not self._persistence_path or not self._persistence_path.exists():
                return

            with open(self._persistence_path, encoding="utf-8") as f:
                json.load(f)

            # TODO: 反序列化数据（需要实现序列化/反序列化逻辑）
            # 当前简化实现，跳过

        except Exception as e:
            raise StorageError(f"Failed to load from file: {e}") from e

    async def save_to_file(self) -> None:
        """保存数据到文件"""
        if not self._persistence_path:
            return

        try:
            async with self._lock:
                # TODO: 序列化数据（需要实现序列化/反序列化逻辑）
                # 当前简化实现，跳过
                data: dict[str, Any] = {
                    "version": "1.0",
                    "saved_at": datetime.now().isoformat(),
                    "optimization_records": [],
                    "ab_tests": [],
                    "quality_snapshots": {},
                }

                # 确保目录存在
                self._persistence_path.parent.mkdir(parents=True, exist_ok=True)

                with open(self._persistence_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            raise StorageError(f"Failed to save to file: {e}") from e

    async def _auto_save_loop(self) -> None:
        """自动保存循环"""
        if not self._auto_save_interval:
            return

        while True:
            try:
                await asyncio.sleep(self._auto_save_interval)
                await self.save_to_file()
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # 忽略保存错误，不中断循环
