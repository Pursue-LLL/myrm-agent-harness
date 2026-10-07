"""跨设备会话实时漫游、团队协作接力与沙箱热镜像套件强类型契约定义。

[INPUT]
- 无外部动态依赖，定义协作角色枚举、跨端断点模型、团队接力共享包与克隆接力结果契约。

[OUTPUT]
- CollaborationRole: 协作角色枚举 (OWNER, DRIVER, OBSERVER)
- DevicePlatform: 客户端设备平台枚举 (MAC, PC, WEB, MOBILE)
- SessionRoamingBreakpoint: 跨端漫游断点与草稿状态契约
- SandboxWarmMirrorSpec: 沙箱执行环境热镜像规格契约
- ExecutableTeamShareBundle: 团队可执行接力共享包契约
- ForkAndContinueResult: 单键分叉并继续执行结果契约

[POS]
- 位于 context_management/session_roaming/session_roaming_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum


class CollaborationRole(StrEnum):
    """团队协作权限角色三级模型（对齐 Multiplayer 架构演进）。"""

    OWNER = "owner"        # 所有者：完全控制、权限变更、撤回与归档
    DRIVER = "driver"      # 共驾者：实时对话接力、输入指令、触发工具执行
    OBSERVER = "observer"  # 旁观者：实时只读同步思维链与产物，禁止指令注入


class DevicePlatform(StrEnum):
    """客户端设备平台类型枚举。"""

    MAC = "mac"
    PC = "pc"
    WEB = "web"
    MOBILE = "mobile"


@dataclass(frozen=True)
class SessionRoamingBreakpoint:
    """跨设备会话实时漫游断点契约。"""

    session_id: str
    client_device_id: str
    platform: DevicePlatform
    cursor_message_index: int
    pending_draft_input: str
    active_background_task_count: int
    environment_snapshot: dict[str, str]
    sequence_number: int  # 递增单调序列号，防止并发时旧设备覆盖新状态
    updated_at_iso: str


@dataclass(frozen=True)
class SandboxWarmMirrorSpec:
    """沙箱执行环境热镜像元数据契约。"""

    workspace_root: str
    mounted_artifacts: tuple[str, ...]
    sanitized_env_keys: tuple[str, ...]
    clone_isolation_mode: str  # "ephemeral_clone" | "persistent_volume"
    created_at_iso: str


@dataclass(frozen=True)
class ExecutableTeamShareBundle:
    """带执行沙箱热镜像的团队安全共享包契约。"""

    share_id: str
    original_session_id: str
    creator_user_id: str
    default_role: CollaborationRole
    sandbox_mirror: SandboxWarmMirrorSpec
    token_redacted: bool
    allowed_domains: tuple[str, ...]
    expires_at_iso: str
    share_url: str


@dataclass(frozen=True)
class ForkAndContinueResult:
    """单键分叉并接续执行结果契约。"""

    forked_session_id: str
    parent_session_id: str
    operator_user_id: str
    assigned_role: CollaborationRole
    cloned_message_count: int
    new_sandbox_workspace_root: str
    resumed_cursor_index: int
    created_at_iso: str
