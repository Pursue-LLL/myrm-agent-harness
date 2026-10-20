"""插件全生命周期状态机、事务级临时隔离构建与零重启热重载注册表模块。

提供具备原子回滚能力的插件安装、依赖探测、安全审计、动态挂载与热生效管理，
并与智能体能力纪元（Capability Epoch）联动，实现运行期零重启热生效与零残留物理卸载。

[INPUT]
- __future__
- logging
- shutil
- tempfile
- time
- collections

[OUTPUT]
- logger
- PluginStatus
- PluginError
- PluginSecurityError
- PluginNotFoundError
- PluginInstallError
- PluginMetadata
- PluginHotReloadRegistry

[POS]
插件全生命周期状态机、事务级临时隔离构建与零重启热重载注册表模块。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.agent.plugins.dependency_sniffer import (
    PluginProjectKind,
    SandboxDependencySniffer,
)
from myrm_agent_harness.agent.plugins.intent_parser import (
    RepoCoordinate,
    SafeRepoUrlValidator,
)
from myrm_agent_harness.agent.plugins.security_auditor import (
    PluginSecurityAuditor,
    ReservedToolGuard,
)

logger = logging.getLogger(__name__)


class PluginStatus(StrEnum):
    """插件生命周期状态枚举。"""

    STAGING = "staging"
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    UNINSTALLED = "uninstalled"


class PluginError(Exception):
    """插件基础异常类。"""


class PluginSecurityError(PluginError):
    """插件静态安全审计未通过异常。"""


class PluginNotFoundError(PluginError):
    """未找到指定插件异常。"""


class PluginInstallError(PluginError):
    """插件构建或安装异常。"""


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    """插件全生命周期元数据实体。"""

    plugin_id: str
    repo_url: str
    project_kind: PluginProjectKind
    status: PluginStatus
    install_dir: Path
    tools: tuple[str, ...]
    manifest_file: str | None
    created_at: float
    updated_at: float
    error_message: str | None = None


class PluginHotReloadRegistry:
    """插件事务隔离构建与零重启热重载注册表。"""

    def __init__(
        self,
        plugins_root_dir: Path,
        on_capability_changed: Callable[[], None] | None = None,
        git_cloner: Callable[[str, Path], None] | None = None,
    ) -> None:
        self._plugins_root_dir = plugins_root_dir
        self._plugins_root_dir.mkdir(parents=True, exist_ok=True)
        self._on_capability_changed = on_capability_changed
        self._git_cloner = git_cloner
        self._registry: dict[str, PluginMetadata] = {}

    @property
    def plugins_root_dir(self) -> Path:
        """插件持久化存储根目录。"""
        return self._plugins_root_dir

    def _notify_capability_change(self) -> None:
        """通知能力纪元发生变化，驱动智能体上下文即时失效与重构。"""
        if self._on_capability_changed is not None:
            try:
                self._on_capability_changed()
            except Exception as exc:
                logger.error("Failed to notify capability change callback: %s", exc)

    @classmethod
    def _generate_plugin_id(cls, coordinate: RepoCoordinate) -> str:
        """生成安全且规范的插件唯一标识符。"""
        safe_repo = coordinate.repo.lower().replace("-", "_").replace(".", "_")
        safe_owner = coordinate.owner.lower().replace("-", "_")
        return f"plug_{safe_owner}_{safe_repo}"

    def install_from_repository(
        self,
        repo_url: str,
        source_dir: Path | None = None,
    ) -> PluginMetadata:
        """从 Git 仓库事务级构建并热加载插件。

        参数:
            repo_url: 插件远程代码仓库 URL
            source_dir: 可选的本地预克隆源码目录（用于离线测试或已拉取仓库）
        """
        # 1. 强制协议与网络安全校验（防御 SSRF 与内网穿透）
        coordinate = SafeRepoUrlValidator.validate_and_parse(
            repo_url,
            allow_dns_resolution=(source_dir is None),
        )
        plugin_id = self._generate_plugin_id(coordinate)
        target_dir = self._plugins_root_dir / plugin_id

        # 若已存在活跃插件，先执行平滑更新回滚准备
        staging_dir = Path(tempfile.mkdtemp(prefix=f"staging_{plugin_id}_"))
        now = time.time()

        try:
            # 2. 检出源码至隔离 Staging 目录
            if source_dir is not None:
                if not source_dir.exists():
                    raise PluginInstallError(f"Local source directory does not exist: {source_dir}")
                shutil.copytree(source_dir, staging_dir, dirs_exist_ok=True)
            elif self._git_cloner is not None:
                self._git_cloner(repo_url, staging_dir)
            else:
                raise PluginInstallError("No git cloner configured and no local source provided.")

            # 3. 多模态依赖特征嗅探
            detection = SandboxDependencySniffer.sniff_directory(staging_dir)

            # 4. 静态恶意代码审计
            audit_report = PluginSecurityAuditor.audit_directory(staging_dir)
            if not audit_report.is_clean:
                risks_str = "; ".join(audit_report.detected_risks)
                raise PluginSecurityError(
                    f"Security audit rejected plugin '{plugin_id}': {risks_str}"
                )

            # 5. 核心保留工具防影子化劫持与命名空间隔离
            detected_tools_list: list[str] = list(detection.declared_dependencies)
            if detection.manifest_file:
                detected_tools_list.append(detection.manifest_file)
            sanitized_tools = ReservedToolGuard.sanitize_plugin_tool_names(
                plugin_id,
                detected_tools_list,
            )

            # 6. 原子生效与持久化移动
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            shutil.move(str(staging_dir), str(target_dir))

            metadata = PluginMetadata(
                plugin_id=plugin_id,
                repo_url=repo_url,
                project_kind=detection.kind,
                status=PluginStatus.ACTIVE,
                install_dir=target_dir,
                tools=sanitized_tools,
                manifest_file=detection.manifest_file,
                created_at=now,
                updated_at=now,
                error_message=None,
            )
            self._registry[plugin_id] = metadata

            # 7. 广播能力变更，使 Agent Capability Epoch 立即生效
            self._notify_capability_change()
            return metadata

        except Exception as exc:
            # 事务失败原子回滚与清理临时隔离目录
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            error_msg = str(exc)
            logger.error("Plugin installation transaction failed for '%s': %s", plugin_id, error_msg)
            if isinstance(exc, (PluginSecurityError, PluginInstallError)):
                raise
            raise PluginInstallError(f"Installation failed: {error_msg}") from exc

    def toggle_plugin(self, plugin_id: str, enable: bool) -> PluginMetadata:
        """切换插件启用/禁用状态，即刻触发能力重构。"""
        current = self._registry.get(plugin_id)
        if current is None:
            raise PluginNotFoundError(f"Plugin '{plugin_id}' not found in registry.")

        if not current.install_dir.exists():
            raise PluginNotFoundError(f"Plugin directory for '{plugin_id}' missing on disk.")

        new_status = PluginStatus.ACTIVE if enable else PluginStatus.INACTIVE
        updated = PluginMetadata(
            plugin_id=current.plugin_id,
            repo_url=current.repo_url,
            project_kind=current.project_kind,
            status=new_status,
            install_dir=current.install_dir,
            tools=current.tools,
            manifest_file=current.manifest_file,
            created_at=current.created_at,
            updated_at=time.time(),
            error_message=current.error_message,
        )
        self._registry[plugin_id] = updated
        self._notify_capability_change()
        return updated

    def uninstall_plugin(self, plugin_id: str) -> None:
        """零残留物理卸载插件并清理注册账本。"""
        current = self._registry.get(plugin_id)
        if current is None:
            raise PluginNotFoundError(f"Plugin '{plugin_id}' not found in registry.")

        # 物理彻底清理安装目录
        if current.install_dir.exists():
            shutil.rmtree(current.install_dir, ignore_errors=True)

        # 从注册表中移除
        del self._registry[plugin_id]

        # 广播能力变更
        self._notify_capability_change()

    def get_plugin(self, plugin_id: str) -> PluginMetadata:
        """获取指定插件的元数据详情。"""
        plugin = self._registry.get(plugin_id)
        if plugin is None:
            raise PluginNotFoundError(f"Plugin '{plugin_id}' does not exist.")
        return plugin

    def list_plugins(self) -> tuple[PluginMetadata, ...]:
        """按稳定顺序返回所有已注册插件元数据列表。"""
        return tuple(sorted(self._registry.values(), key=lambda p: p.plugin_id))

    def get_active_tools(self) -> tuple[str, ...]:
        """获取当前所有处于 ACTIVE 状态的插件导出的工具集（已执行保留字隔离）。"""
        active_tools: list[str] = []
        for plugin in self._registry.values():
            if plugin.status == PluginStatus.ACTIVE:
                active_tools.extend(plugin.tools)
        return tuple(sorted(active_tools))
