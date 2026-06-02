"""Infrastructure security module.

提供通用的安全基础设施：
- signature: 请求签名验证（HMAC-SHA256）
- nonce: 防重放攻击（内存存储）

设计原则：
1. 通用性优先：与业务逻辑完全解耦
2. 零业务依赖：不感知用户ID、会话ID等业务概念
3. 开箱即用：任何使用框架的项目都可直接使用
"""

from .nonce import NonceManager, nonce_manager
from .signature import SignatureVerifier, TimestampVerifier

__all__ = [
    "NonceManager",
    "SignatureVerifier",
    "TimestampVerifier",
    "nonce_manager",
]
