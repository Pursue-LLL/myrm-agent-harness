"""强类型契约定义：具备交互式运行时状态的会话免密分享链接、多端只读/协作穿透与一键无损分叉套件。

[INPUT]
- 无外部动态依赖，定义分享权限枚举、带签名凭证、透视视口数据与无损分叉结果契约。

[OUTPUT]
- ShareAccessPermission: 会话分享访问权限枚举 (只读透视 / 允许无损分叉)
- ShareTokenPayload: 密码学带签名会话分享凭证契约
- SharedSessionPerspective: 高保真交互式只读透视视口契约
- LosslessForkResult: 一键无损分叉接力结果契约
- ShareableForkConfig: 会话分享签名与生命周期配置契约

[POS]
- 位于 context_management/shareable_fork/shareable_fork_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class ShareAccessPermission(StrEnum):
    """会话分享访问权限。"""

    READ_ONLY_VIEW = "read_only_view"
    ALLOW_INTERACTIVE_FORK = "allow_interactive_fork"


@dataclass(frozen=True)
class ShareTokenPayload:
    """带 HMAC-SHA256 密码学签名的会话免密分享凭证契约。"""

    share_id: str
    session_id: str
    issuer_id: str
    permission: ShareAccessPermission
    include_artifacts: bool
    expires_at_iso: str
    signature_hmac: str


@dataclass(frozen=True)
class SharedSessionPerspective:
    """高保真交互式会话透视视口快照契约。"""

    share_id: str
    session_id: str
    session_title: str
    messages_snapshot: tuple[tuple[str, str], ...]  # (role, content)
    artifacts_snapshot: tuple[tuple[str, str], ...]  # (name, uri)
    execution_trace_summary: str
    can_fork: bool
    expires_at_iso: str


@dataclass(frozen=True)
class LosslessForkResult:
    """一键无损分叉接力克隆结果契约。"""

    forked_session_id: str
    original_session_id: str
    forked_by_user_id: str
    copied_message_count: int
    copied_artifact_count: int
    new_session_uri: str
    forked_at_iso: str


@dataclass
class ShareableForkConfig:
    """会话分享签名与生命周期配置契约。"""

    secret_key: str = "myrm_secure_share_signing_salt_2026"
    default_ttl_seconds: int = 604800  # 7 天默认有效期
    max_messages_snapshot: int = 500
    allow_cross_tenant_fork: bool = False
