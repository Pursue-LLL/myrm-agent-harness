"""Shared Artifact Vault

实现多智能体共享大文件存储的 UUID 指针协议 (vault://<uuid>), 解决大模型上下文爆炸.
通过将大型结果落盘并只交换指针, 实现零拷贝数据传输.

[INPUT]
- myrm_agent_harness.agent.security.path_security::safe_join_path (POS: 路径安全与边界守卫模块)
- myrm_agent_harness.core.artifacts.paths::resolve_workspace_artifact_vault_dir (POS: workspace artifact vault path SSOT)

[OUTPUT]
- VaultObject: class — Vault Object
- ArtifactVault: class — Artifact Vault

[POS]
Shared Artifact Vault
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from myrm_agent_harness.core.artifacts.paths import resolve_workspace_artifact_vault_dir

logger = logging.getLogger(__name__)

VAULT_PREFIX = "vault://"


@dataclass
class VaultObject:
    """Vault 中存储的对象元数据"""

    id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: float
    sha256_hash: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ArtifactVault:
    """多智能体共享的巨型工件金库.

    Default uses ``{workspace}/.agent/vault`` (see ``core.artifacts.paths``).
    """

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root)
        self.vault_dir = resolve_workspace_artifact_vault_dir(self.workspace_root)
        self.objects_dir = self.vault_dir / "objects"
        self.meta_dir = self.vault_dir / "meta"

        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def get_object_path(self, obj_id: str) -> Path:
        from myrm_agent_harness.agent.security.path_security import safe_join_path

        return safe_join_path(self.objects_dir, obj_id)

    def _get_meta_path(self, obj_id: str) -> Path:
        from myrm_agent_harness.agent.security.path_security import safe_join_path

        return safe_join_path(self.meta_dir, f"{obj_id}.json")

    def put(
        self,
        content: str | bytes,
        filename: str,
        content_type: str | None = None,
        description: str = "",
    ) -> str:
        """存入一个对象, 返回 vault:// 指针"""
        import fcntl
        import hashlib
        import mimetypes

        if not content_type:
            guessed_type, _ = mimetypes.guess_type(filename)
            content_type = guessed_type or "application/octet-stream"

        obj_id = str(uuid4())

        obj_path = self.get_object_path(obj_id)

        # 使用流式计算 Hash 并写入文件以防止 OOM
        sha256_hash_obj = hashlib.sha256()
        size_bytes = 0

        with open(obj_path, "wb") as f:
            # 加上排他锁, 防止并发写入导致文件损坏
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                if isinstance(content, str):
                    # 字符串较小, 直接写入
                    content_bytes = content.encode("utf-8")
                    f.write(content_bytes)
                    sha256_hash_obj.update(content_bytes)
                    size_bytes = len(content_bytes)
                else:
                    # 字节流可能很大, 直接写入并计算
                    f.write(content)
                    sha256_hash_obj.update(content)
                    size_bytes = len(content)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        sha256_hash = sha256_hash_obj.hexdigest()

        meta = VaultObject(
            id=obj_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            created_at=time.time(),
            sha256_hash=sha256_hash,
            description=description,
        )

        self._get_meta_path(obj_id).write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Vault 存入大文件: %s (%d bytes) -> %s%s",
            filename,
            size_bytes,
            VAULT_PREFIX,
            obj_id,
        )
        return f"{VAULT_PREFIX}{obj_id}"

    def put_file(
        self,
        file_path: str | Path,
        filename: str,
        content_type: str | None = None,
        description: str = "",
    ) -> str:
        """从本地文件路径存入一个大文件对象, 返回 vault:// 指针.

        使用流式读取和计算 Hash, 防止读取大文件时 OOM.
        """
        import fcntl
        import hashlib
        import mimetypes

        if not content_type:
            guessed_type, _ = mimetypes.guess_type(filename)
            content_type = guessed_type or "application/octet-stream"

        source_path = Path(file_path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        obj_id = str(uuid4())
        obj_path = self.get_object_path(obj_id)

        sha256_hash_obj = hashlib.sha256()
        size_bytes = 0

        # 流式读取源文件, 计算 Hash 并写入目标文件
        with open(source_path, "rb") as src_f, open(obj_path, "wb") as dst_f:
            fcntl.flock(dst_f, fcntl.LOCK_EX)
            try:
                for chunk in iter(lambda: src_f.read(8192), b""):
                    dst_f.write(chunk)
                    sha256_hash_obj.update(chunk)
                    size_bytes += len(chunk)
            finally:
                fcntl.flock(dst_f, fcntl.LOCK_UN)

        sha256_hash = sha256_hash_obj.hexdigest()

        meta = VaultObject(
            id=obj_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            created_at=time.time(),
            sha256_hash=sha256_hash,
            description=description,
        )

        self._get_meta_path(obj_id).write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Vault 从文件存入大对象: %s (%d bytes) -> %s%s",
            filename,
            size_bytes,
            VAULT_PREFIX,
            obj_id,
        )
        return f"{VAULT_PREFIX}{obj_id}"

    def get(self, uri: str) -> bytes:
        """从 vault:// 指针读取内容"""
        if not uri.startswith(VAULT_PREFIX):
            raise ValueError(
                f"Invalid Vault URI: {uri}. Must start with {VAULT_PREFIX}"
            )

        obj_id = uri[len(VAULT_PREFIX) :]
        obj_path = self.get_object_path(obj_id)
        if not obj_path.exists():
            raise FileNotFoundError(f"Vault object not found: {obj_id}")

        return obj_path.read_bytes()

    def get_meta(self, uri: str) -> VaultObject | None:
        """读取对象元数据"""
        if not uri.startswith(VAULT_PREFIX):
            return None

        obj_id = uri[len(VAULT_PREFIX) :]
        meta_path = self._get_meta_path(obj_id)
        if not meta_path.exists():
            return None

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return VaultObject(**data)

    def list_objects(self) -> list[VaultObject]:
        """列出所有的金库对象"""
        objects = []
        for meta_file in self.meta_dir.glob("*.json"):
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                objects.append(VaultObject(**data))
            except Exception as e:
                logger.warning("Failed to read vault meta %s: %s", meta_file, e)

        # 按创建时间降序
        objects.sort(key=lambda x: x.created_at, reverse=True)
        return objects

    def save_manifest(self, manifest_data: dict[str, object]) -> Path:
        """持久化交付包 Manifest (manifest.json) 到 Vault 的 bundles 目录"""
        from myrm_agent_harness.agent.security.path_security import safe_join_path

        bundles_dir = self.vault_dir / "bundles"
        bundles_dir.mkdir(parents=True, exist_ok=True)

        bundle_id = str(manifest_data.get("bundle_id", "default"))
        manifest_path = safe_join_path(bundles_dir, f"{bundle_id}.json")
        manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest_path

    def get_manifest(self, bundle_id: str) -> dict[str, object] | None:
        """从 Vault 的 bundles 目录读取指定 bundle_id 的 manifest 数据"""
        from myrm_agent_harness.agent.security.path_security import safe_join_path

        bundles_dir = self.vault_dir / "bundles"
        manifest_path = safe_join_path(bundles_dir, f"{bundle_id}.json")
        if not manifest_path.exists() or not manifest_path.is_file():
            return None

        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def purge_object(self, uri_or_id: str) -> bool:
        """从金库物理删除单个对象（包含文件与元数据）。

        Args:
            uri_or_id: 对象 UUID 或以 'vault://' 开头的 URI 指针。

        Returns:
            若对象存在且成功删除返回 True，否则返回 False。
        """
        obj_id = uri_or_id[len(VAULT_PREFIX) :] if uri_or_id.startswith(VAULT_PREFIX) else uri_or_id
        obj_path = self.get_object_path(obj_id)
        meta_path = self._get_meta_path(obj_id)

        deleted = False
        try:
            if obj_path.exists():
                obj_path.unlink(missing_ok=True)
                deleted = True
            if meta_path.exists():
                meta_path.unlink(missing_ok=True)
                deleted = True
        except OSError as e:
            logger.warning("Failed to purge vault object %s: %s", obj_id, e)
            return False

        if deleted:
            logger.debug("Purged vault object: %s", obj_id)
        return deleted

    def purge_objects(self, uri_or_ids: list[str]) -> int:
        """批量物理删除指定对象。

        Args:
            uri_or_ids: 对象 UUID 或 URI 列表。

        Returns:
            成功物理删除的对象计数。
        """
        count = 0
        for uid in uri_or_ids:
            if self.purge_object(uid):
                count += 1
        return count

    def purge_by_task_id(self, task_id: str) -> int:
        """清理特定任务生成的所有金库对象（如 subagent_{task_id}.md 等）。

        Args:
            task_id: 关联的任务 ID 或会话 ID 标识。

        Returns:
            物理释放的对象数量。
        """
        if not task_id:
            return 0

        target_pattern = f"subagent_{task_id}"
        purged = 0
        for obj in self.list_objects():
            if target_pattern in obj.filename or target_pattern in obj.description or task_id in obj.id:
                if self.purge_object(obj.id):
                    purged += 1

        if purged > 0:
            logger.info("Purged %d vault objects for task_id: %s", purged, task_id)
        return purged

    def purge_all(self) -> int:
        """清空金库中所有对象及元数据（用于测试隔离或会话彻底重置）。"""
        count = 0
        for obj in self.list_objects():
            if self.purge_object(obj.id):
                count += 1
        return count

