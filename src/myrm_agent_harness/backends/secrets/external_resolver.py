"""External secret reference resolver facade.

[INPUT]
- toolkits.llms.secrets::resolve_external_secret (POS: Framework-neutral secret reference resolution, stdlib-only Zero-Disk resolver)

[OUTPUT]
- resolve_external_secret: 解析 op:// 与 bw:// 外部凭据引用（零落盘内存解析）
- is_external_secret_reference: 判定给定值是否为外部凭据引用 URI
- ExternalSecretResolutionError: 外部凭据解析失败异常

[POS]
backends/secrets 的外部凭据解析统一门面。将框架中立的解析能力重新导出给 backends 层，避免调用方直接下沉依赖 toolkits。
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.secrets import (
    ExternalSecretResolutionError,
    is_external_secret_reference,
    resolve_external_secret,
)

__all__ = [
    "ExternalSecretResolutionError",
    "is_external_secret_reference",
    "resolve_external_secret",
]
