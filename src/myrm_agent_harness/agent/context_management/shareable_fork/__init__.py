"""具备交互式运行时状态的会话免密分享链接、多端只读/协作穿透与一键无损分叉套件。

导出的主要类与契约：
- InteractiveShareableForkEngine: 交互式会话分享与无损分叉中枢引擎
- LosslessForkResult: 一键无损分叉接力结果契约
- ShareAccessPermission: 会话分享访问权限枚举
- ShareTokenPayload: 密码学带签名会话分享凭证契约
- ShareableForkConfig: 会话分享签名与生命周期配置契约
- SharedSessionPerspective: 高保真交互式只读透视视口契约
"""

from .interactive_shareable_fork_engine import InteractiveShareableForkEngine
from .shareable_fork_types import (
    LosslessForkResult,
    ShareAccessPermission,
    ShareTokenPayload,
    ShareableForkConfig,
    SharedSessionPerspective,
)

__all__ = [
    "InteractiveShareableForkEngine",
    "LosslessForkResult",
    "ShareAccessPermission",
    "ShareTokenPayload",
    "ShareableForkConfig",
    "SharedSessionPerspective",
]
