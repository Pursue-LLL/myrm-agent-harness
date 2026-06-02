"""配置预设系统

提供内置的配置预设（development, production, saas），帮助用户快速启动 Agent。

[INPUT]

[OUTPUT]
- ConfigPreset: 配置预设数据类
- BUILTIN_PRESETS: 内置预设字典

[POS]
Configuration presets layer. Provides best-practice configuration presets for common scenarios.

"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import StorageConfig


@dataclass(frozen=True, slots=True)
class ConfigPreset:
    """配置预设

    纯数据类，不包含业务逻辑。框架层提供预设，业务层使用预设。
    """

    name: str
    """预设名称"""

    description: str
    """预设描述"""

    config_dict: dict[str, object]
    """配置字典（不包含 LLM 配置）"""


# 内置预设
BUILTIN_PRESETS: dict[str, ConfigPreset] = {
    "development": ConfigPreset(
        name="development",
        description="Development environment: fast iteration, verbose logging, relaxed limits",
        config_dict={
            "recursion_limit": 200,  # 宽松限制，方便调试
            "enable_artifacts": True,
            "artifacts_output_path": "./artifacts",
            "storage_config": StorageConfig(
                backend_type="local",
                root_dir="./workspace",
                virtual_mode=True,  # 沙箱开启
            ),
        },
    ),
    "production": ConfigPreset(
        name="production",
        description="Production environment: stable, secure, performant, strict limits",
        config_dict={
            "recursion_limit": 50,  # 严格限制
            "timeout_seconds": 300,  # 5分钟超时
            "enable_artifacts": False,  # 禁用工件（安全）
            "storage_config": StorageConfig(backend_type="local", root_dir="./workspace", virtual_mode=True),
        },
    ),
    "saas": ConfigPreset(
        name="saas",
        description="SaaS multi-tenant environment: isolated, scalable, monitored",
        config_dict={
            "recursion_limit": 100,  # 中等限制
            "timeout_seconds": 600,  # 10分钟超时
            "enable_artifacts": True,
            "artifacts_output_path": "/shared/artifacts",  # 共享存储
            "storage_config": StorageConfig(
                backend_type="custom",  # 业务层提供自定义存储
                root_dir="./workspace",
                virtual_mode=True,
            ),
        },
    ),
}


__all__ = [
    "BUILTIN_PRESETS",
    "ConfigPreset",
]
