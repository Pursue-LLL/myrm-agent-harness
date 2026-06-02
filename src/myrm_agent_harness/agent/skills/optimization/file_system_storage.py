"""File System Storage Implementation

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillOptimizationStorage (POS: 存储层接口)
- .protocols.OptimizationRecord (POS: 优化记录协议)
- .types.SkillQualityScore (POS: 质量评分数据类)
- .types.SkillVersion (POS: 版本数据类)
- json (POS: 序列化)
- pathlib (POS: 文件路径处理)
- aiofiles (POS: 异步文件操作)

[OUTPUT]
- FileSystemStorage: 基于本地文件系统的存储实现类

[POS]
File system storage (framework layer). Ready-to-use persistent storage implementation.

"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .protocols import OptimizationRecord, SkillOptimizationStorage
from .types import SkillQualityScore, SkillVersion

logger = logging.getLogger(__name__)


class FileSystemStorage(SkillOptimizationStorage):
    """基于文件系统的持久化存储

    完美契合 Agent in Sandbox 的 Volume 概念。
    数据存储结构：
    .myrm/optimization/
    ├── records/
    │   ├── skill_a.jsonl
    │   └── skill_b.jsonl
    ├── versions/
    │   ├── skill_a.json
    │   └── skill_b.json
    └── quality/
        ├── skill_a.json
        └── skill_b.json

    Args:
        base_path: 存储根目录，默认为当前目录下的 .myrm/optimization
    """

    def __init__(self, base_path: str | Path = ".myrm/optimization"):
        self.base_path = Path(base_path)
        self.records_dir = self.base_path / "records"
        self.versions_dir = self.base_path / "versions"
        self.quality_dir = self.base_path / "quality"

        # Ensure directories exist
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.quality_dir.mkdir(parents=True, exist_ok=True)

    def _get_record_file(self, skill_id: str) -> Path:
        # Sanitize skill_id for filename
        safe_id = skill_id.replace("/", "_").replace("\\", "_")
        return self.records_dir / f"{safe_id}.jsonl"

    def _get_version_file(self, skill_id: str) -> Path:
        safe_id = skill_id.replace("/", "_").replace("\\", "_")
        return self.versions_dir / f"{safe_id}.json"

    def _get_quality_file(self, skill_id: str) -> Path:
        safe_id = skill_id.replace("/", "_").replace("\\", "_")
        return self.quality_dir / f"{safe_id}.json"

    def _get_lock(self, file_path: Path) -> Any:
        """获取异步文件锁"""
        from filelock import AsyncFileLock

        lock_path = str(file_path) + ".lock"
        return AsyncFileLock(lock_path, timeout=10.0)

    async def save_optimization_record(self, record: OptimizationRecord) -> None:
        """保存优化记录到 JSONL 文件"""
        import aiofiles

        file_path = self._get_record_file(record.skill_id)
        lock = self._get_lock(file_path)

        # Convert record to dict, handling datetime serialization
        data = {
            "skill_id": record.skill_id,
            "skill_type": record.skill_type,
            "baseline_score": asdict(record.baseline_score),
            "optimized_content": record.optimized_content,
            "security_validation": record.security_validation,
            "status": record.status,
            "started_at": record.started_at.isoformat(),
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "error_message": record.error_message,
        }

        async with lock, aiofiles.open(file_path, mode="a", encoding="utf-8") as f:
            await f.write(json.dumps(data) + "\n")

    async def get_recent_optimizations(self, skill_id: str, limit: int = 5) -> list[OptimizationRecord]:
        """获取最近的优化记录"""
        import aiofiles

        from myrm_agent_harness.agent.skills.optimization.types import OptimizationResult

        file_path = self._get_record_file(skill_id)
        if not file_path.exists():
            return []

        records = []
        lock = self._get_lock(file_path)

        async with lock, aiofiles.open(file_path, encoding="utf-8") as f:
            lines = await f.readlines()

        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Reconstruct OptimizationResult
                baseline_score = SkillQualityScore(**data["baseline_score"])
                started_at = datetime.fromisoformat(data["started_at"])
                completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None

                record = OptimizationResult(
                    skill_type=data["skill_type"],
                    baseline_score=baseline_score,
                    optimized_content=data["optimized_content"],
                    security_validation=data["security_validation"],
                    status=data["status"],
                    started_at=started_at,
                )
                record.skill_id = data["skill_id"]
                record.completed_at = completed_at
                record.error_message = data.get("error_message")

                records.append(record)
                if len(records) >= limit:
                    break
            except Exception as e:
                logger.warning(f"Failed to parse optimization record in {file_path}: {e}")

        return records

    async def get_last_optimization_time(self, skill_id: str) -> datetime | None:
        """获取最后一次优化时间"""
        records = await self.get_recent_optimizations(skill_id, limit=1)
        if records and records[0].completed_at:
            return records[0].completed_at
        return None

    async def save_quality_snapshot(self, skill_id: str, quality: SkillQualityScore) -> None:
        """保存质量快照"""
        import aiofiles

        file_path = self._get_quality_file(skill_id)
        lock = self._get_lock(file_path)

        data = {"timestamp": datetime.utcnow().isoformat(), "quality": asdict(quality)}

        async with lock, aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=2))

    async def get_quality_snapshot(self, skill_id: str) -> SkillQualityScore | None:
        """获取最新的质量快照"""
        import aiofiles

        file_path = self._get_quality_file(skill_id)
        if not file_path.exists():
            return None

        lock = self._get_lock(file_path)
        try:
            async with lock, aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()

            data = json.loads(content)
            return SkillQualityScore(**data["quality"])
        except Exception as e:
            logger.warning(f"Failed to read quality snapshot for {skill_id}: {e}")
            return None

    async def get_quality_history(self, skill_id: str, days: int = 30) -> list[dict[str, Any]]:
        """获取质量历史 (FileSystemStorage 仅保留最新快照，历史需由 Server 层实现)

        注意：为了保持 Harness 轻量，FileSystemStorage 不维护重度的历史时间序列。
        如果需要完整的历史趋势图，请使用 Server 层的 HeavyAnalyticsRepository。
        这里仅返回最新的一个快照点，以满足基本接口契约。
        """
        snapshot = await self.get_quality_snapshot(skill_id)
        if not snapshot:
            return []

        file_path = self._get_quality_file(skill_id)
        stat = file_path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime)

        return [{"timestamp": mtime.isoformat(), "quality_score": asdict(snapshot)}]

    async def save_skill_version(self, version: SkillVersion) -> None:
        """保存 skill 版本"""
        import aiofiles

        file_path = self._get_version_file(version.skill_id)
        lock = self._get_lock(file_path)

        async with lock:
            # Read existing versions
            versions_data = []
            if file_path.exists():
                try:
                    async with aiofiles.open(file_path, encoding="utf-8") as f:
                        content = await f.read()
                        if content.strip():
                            versions_data = json.loads(content)
                except Exception:
                    pass

            # Convert version to dict
            version_dict = asdict(version)
            version_dict["created_at"] = version.created_at.isoformat()

            # If active, deactivate others
            if version.is_active:
                for v in versions_data:
                    v["is_active"] = False

            # Update or append
            updated = False
            for i, v in enumerate(versions_data):
                if v["version_id"] == version.version_id:
                    versions_data[i] = version_dict
                    updated = True
                    break

            if not updated:
                versions_data.append(version_dict)

            # Write back
            async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                await f.write(json.dumps(versions_data, indent=2))

    async def get_skill_version(self, skill_id: str, version_id: str) -> SkillVersion | None:
        """获取特定版本"""
        import aiofiles

        file_path = self._get_version_file(skill_id)
        if not file_path.exists():
            return None

        lock = self._get_lock(file_path)
        try:
            async with lock, aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()

            versions_data = json.loads(content)

            for v_data in versions_data:
                if v_data["version_id"] == version_id:
                    v_data["created_at"] = datetime.fromisoformat(v_data["created_at"])
                    # Handle nested quality score
                    if v_data.get("quality_score"):
                        v_data["quality_score"] = SkillQualityScore(**v_data["quality_score"])
                    return SkillVersion(**v_data)
        except Exception as e:
            logger.warning(f"Failed to read skill version {version_id} for {skill_id}: {e}")

        return None

    async def get_active_version(self, skill_id: str) -> SkillVersion | None:
        """获取当前激活的版本"""
        import aiofiles

        file_path = self._get_version_file(skill_id)
        if not file_path.exists():
            return None

        lock = self._get_lock(file_path)
        try:
            async with lock, aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()

            versions_data = json.loads(content)

            for v_data in versions_data:
                if v_data.get("is_active"):
                    v_data["created_at"] = datetime.fromisoformat(v_data["created_at"])
                    if v_data.get("quality_score"):
                        v_data["quality_score"] = SkillQualityScore(**v_data["quality_score"])
                    return SkillVersion(**v_data)
        except Exception as e:
            logger.warning(f"Failed to read active version for {skill_id}: {e}")

        return None

    async def get_version_history(self, skill_id: str, limit: int = 10) -> list[SkillVersion]:
        """获取版本历史"""
        import aiofiles

        file_path = self._get_version_file(skill_id)
        if not file_path.exists():
            return []

        lock = self._get_lock(file_path)
        try:
            async with lock, aiofiles.open(file_path, encoding="utf-8") as f:
                content = await f.read()

            versions_data = json.loads(content)

            versions = []
            for v_data in versions_data:
                v_data["created_at"] = datetime.fromisoformat(v_data["created_at"])
                if v_data.get("quality_score"):
                    v_data["quality_score"] = SkillQualityScore(**v_data["quality_score"])
                versions.append(SkillVersion(**v_data))

            # Sort by created_at desc
            versions.sort(key=lambda x: x.created_at, reverse=True)
            return versions[:limit]
        except Exception as e:
            logger.warning(f"Failed to read version history for {skill_id}: {e}")
            return []

    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        try:
            # Test write access
            test_file = self.base_path / ".health_check"
            test_file.touch()
            test_file.unlink()

            return {
                "healthy": True,
                "type": "FileSystemStorage",
                "base_path": str(self.base_path),
                "records_dir_exists": self.records_dir.exists(),
                "versions_dir_exists": self.versions_dir.exists(),
            }
        except Exception as e:
            return {"healthy": False, "type": "FileSystemStorage", "error": str(e)}
