"""Skill Security Configuration

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- dataclasses.dataclass (POS: Python数据类装饰器)

[OUTPUT]
- SecurityConfig: 安全验证配置

[POS]
Skill content security validation configuration.

"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SecurityConfig:
    """安全验证配置"""

    # 危险模式列表（正则表达式）
    dangerous_patterns: list[str] = field(
        default_factory=lambda: [
            r"rm\s+-rf",
            r"DROP\s+TABLE",
            r"eval\(",
            r"/etc/passwd",
            r"~/.ssh",
            r"__import__",
            r"exec\(",
            r"os\.system",
            r"subprocess\.",
        ]
    )

    # 是否启用沙箱验证（耗时但更安全）
    enable_sandbox_validation: bool = False

    # 沙箱验证超时（秒）
    sandbox_timeout: float = 10.0
