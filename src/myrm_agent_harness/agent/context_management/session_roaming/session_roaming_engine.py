"""跨设备会话实时漫游、团队协作接力与沙箱热镜像核心引擎。

[INPUT]
- session_roaming_types.py: 契约模型 (CollaborationRole, DevicePlatform, SessionRoamingBreakpoint, SandboxWarmMirrorSpec, ExecutableTeamShareBundle, ForkAndContinueResult)

[OUTPUT]
- DeviceAgnosticSessionRoamingEngine:
  - sync_roaming_breakpoint: 跨端断点时序同步与草稿漫游
  - get_roaming_breakpoint: 获取指定会话最新跨端漫游状态
  - create_executable_team_share: 构建脱敏的团队协作接力包与沙箱热镜像
  - fork_and_continue_session: 单键分叉并接续执行拉起隔离沙箱

[POS]
- 位于 context_management/session_roaming/session_roaming_engine.py
"""

from datetime import datetime, timezone, timedelta
import secrets
import uuid

from .session_roaming_types import (
    CollaborationRole,
    DevicePlatform,
    ExecutableTeamShareBundle,
    ForkAndContinueResult,
    SandboxWarmMirrorSpec,
    SessionRoamingBreakpoint,
)


class DeviceAgnosticSessionRoamingEngine:
    """跨设备会话实时漫游与团队接力协作引擎。"""

    # 常见敏感环境变量关键词模式（用于团队共享时自动脱敏）
    _SENSITIVE_KEY_PATTERNS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "AUTH", "CREDENTIAL")

    def __init__(self, base_share_domain: str = "https://agent.myrm.io") -> None:
        self._base_share_domain = base_share_domain.rstrip("/")
        # 内存断点快照注册表: session_id -> SessionRoamingBreakpoint
        self._roaming_registry: dict[str, SessionRoamingBreakpoint] = {}
        # 团队共享包注册表: share_id -> ExecutableTeamShareBundle
        self._share_registry: dict[str, ExecutableTeamShareBundle] = {}

    def sync_roaming_breakpoint(
        self,
        session_id: str,
        client_device_id: str,
        platform: DevicePlatform,
        cursor_message_index: int,
        pending_draft_input: str,
        active_background_task_count: int,
        environment_snapshot: dict[str, str],
        sequence_number: int,
    ) -> SessionRoamingBreakpoint:
        """跨端同步更新会话断点状态（支持单调时序递增校验，防旧端覆盖新端）。

        Args:
            session_id: 会话全局唯一标识。
            client_device_id: 客户端设备指纹 ID。
            platform: 客户端设备平台类型。
            cursor_message_index: 视图当前聚焦的消息游标索引。
            pending_draft_input: 用户在输入框未发送的草稿文本。
            active_background_task_count: 正在该设备后台运行的异步任务数。
            environment_snapshot: 客户端环境变量快照。
            sequence_number: 客户端递增单调操作序号。

        Returns:
            SessionRoamingBreakpoint: 最终权威断点数据。
        """
        existing = self._roaming_registry.get(session_id)
        if existing and sequence_number <= existing.sequence_number:
            # 序列号小于等于已有版本，忽略过期旧端推送，直接返回已有最新快照
            return existing

        breakpoint_item = SessionRoamingBreakpoint(
            session_id=session_id,
            client_device_id=client_device_id,
            platform=platform,
            cursor_message_index=cursor_message_index,
            pending_draft_input=pending_draft_input,
            active_background_task_count=active_background_task_count,
            environment_snapshot=dict(environment_snapshot),
            sequence_number=sequence_number,
            updated_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        self._roaming_registry[session_id] = breakpoint_item
        return breakpoint_item

    def get_roaming_breakpoint(self, session_id: str) -> SessionRoamingBreakpoint | None:
        """检索指定会话最新的跨设备漫游断点。"""
        return self._roaming_registry.get(session_id)

    def create_executable_team_share(
        self,
        session_id: str,
        creator_user_id: str,
        workspace_root: str,
        mounted_artifacts: tuple[str, ...],
        env_variables: dict[str, str],
        default_role: CollaborationRole = CollaborationRole.DRIVER,
        expiry_hours: int = 72,
    ) -> ExecutableTeamShareBundle:
        """构建带执行沙箱热镜像的团队协作安全共享包。

        自动执行敏感密钥脱敏，生成唯一的团队安全邀请凭据。
        """
        share_id = f"share_{secrets.token_urlsafe(16)}"

        # 1. 过滤并脱敏环境变量（仅保留非敏感白名单键）
        safe_keys: list[str] = []
        for k in env_variables.keys():
            k_upper = k.upper()
            if not any(pattern in k_upper for pattern in self._SENSITIVE_KEY_PATTERNS):
                safe_keys.append(k)

        # 2. 构造沙箱热镜像规格
        now = datetime.now(timezone.utc)
        sandbox_mirror = SandboxWarmMirrorSpec(
            workspace_root=workspace_root,
            mounted_artifacts=mounted_artifacts,
            sanitized_env_keys=tuple(safe_keys),
            clone_isolation_mode="ephemeral_clone",
            created_at_iso=now.isoformat(),
        )

        expires_at = now + timedelta(hours=expiry_hours)
        share_url = f"{self._base_share_domain}/s/{share_id}"

        bundle = ExecutableTeamShareBundle(
            share_id=share_id,
            original_session_id=session_id,
            creator_user_id=creator_user_id,
            default_role=default_role,
            sandbox_mirror=sandbox_mirror,
            token_redacted=True,
            allowed_domains=("*",),
            expires_at_iso=expires_at.isoformat(),
            share_url=share_url,
        )
        self._share_registry[share_id] = bundle
        return bundle

    def fork_and_continue_session(
        self,
        share_id: str,
        operator_user_id: str,
        cloned_messages: tuple[dict[str, str], ...],
    ) -> ForkAndContinueResult:
        """受邀成员一键分叉会话并在隔离的执行沙箱中无损接续对话。

        Args:
            share_id: 团队共享链接凭据 ID。
            operator_user_id: 当前操作者用户 ID。
            cloned_messages: 继承的父会话消息历史。

        Returns:
            ForkAndContinueResult: 包含全新会话 ID 与沙箱环境的接力结果。
        """
        bundle = self._share_registry.get(share_id)
        if not bundle:
            raise KeyError(f"共享凭据 {share_id} 不存在或已过期销毁。")

        # 检查是否过期
        now_iso = datetime.now(timezone.utc).isoformat()
        if now_iso > bundle.expires_at_iso:
            raise ValueError(f"共享凭据 {share_id} 已于 {bundle.expires_at_iso} 过期。")

        forked_session_id = f"fork_{uuid.uuid4().hex[:12]}"
        # 为接力创建独立对等的沙箱隔离根目录
        new_sandbox_root = f"/sandboxes/fork_{forked_session_id[:8]}"

        # 检索父会话的断点索引（若有）
        parent_bp = self.get_roaming_breakpoint(bundle.original_session_id)
        resumed_cursor = parent_bp.cursor_message_index if parent_bp else len(cloned_messages)

        return ForkAndContinueResult(
            forked_session_id=forked_session_id,
            parent_session_id=bundle.original_session_id,
            operator_user_id=operator_user_id,
            assigned_role=bundle.default_role,
            cloned_message_count=len(cloned_messages),
            new_sandbox_workspace_root=new_sandbox_root,
            resumed_cursor_index=resumed_cursor,
            created_at_iso=now_iso,
        )
