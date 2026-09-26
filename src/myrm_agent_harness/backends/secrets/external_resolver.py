"""External secret reference resolver facade.

[INPUT]
- core.security.external_secrets::resolve_external_secret, invalidate_external_secret,
  is_external_secret_reference, ExternalSecretResolutionError (POS: Foundation security primitive)

[OUTPUT]
- resolve_external_secret: 解析 op:// 与 bw:// 外部凭据引用（零落盘内存缓存解析）
- invalidate_external_secret: 驱逐外部凭据缓存（401/403 轮换自愈）
- is_external_secret_reference: 判定给定值是否为外部凭据引用 URI
- ExternalSecretResolutionError: 外部凭据解析失败异常

[POS]
backends/secrets 的外部凭据解析统一门面。直接从 core.security.external_secrets
导出底层安全原语，保证单向依赖并彻底消除对 toolkits.llms 的反向依赖。
"""

from __future__ import annotations

from myrm_agent_harness.core.security.external_secrets import (
    ExternalSecretResolutionError,
    invalidate_external_secret,
    is_external_secret_reference,
    resolve_external_secret,
)

__all__ = [
    "ExternalSecretResolutionError",
    "invalidate_external_secret",
    "is_external_secret_reference",
    "resolve_external_secret",
]
