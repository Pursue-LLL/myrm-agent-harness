"""配置健康检查系统

提供配置验证和健康检查功能，早期发现配置冲突、危险配置和缺失依赖。

[INPUT]

[OUTPUT]
- ConfigIssue: 配置问题数据类
- check_config_health(): 配置健康检查函数

[POS]
Configuration validation layer. Checks config validity, consistency, and security, producing structured issue reports.

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import AgentConfig


@dataclass(frozen=True, slots=True)
class ConfigIssue:
    """配置问题

    Represents a single configuration issue (error, warning, or info).
    """

    level: str
    """Issue severity: error (blocking), warning (recommended fix), info (suggestion)"""

    message: str
    """Human-readable issue description"""

    field: str | None = None
    """Config field name that caused the issue (optional)"""

    suggestion: str | None = None
    """Suggested fix or workaround (optional)"""


def check_config_health(config: AgentConfig) -> list[ConfigIssue]:
    """检查配置健康状态

    Validates configuration for conflicts, dangerous settings, and missing dependencies.

    Args:
        config: Agent configuration to validate

    Returns:
        List of ConfigIssue (empty if no issues found)

    Categories:
        - Conflicts: Incompatible settings (e.g., enable_artifacts without path)
        - Dangerous: Security risks (e.g., high recursion_limit)
        - Missing deps: Required dependencies not available
        - Performance: Suboptimal settings
    """
    issues: list[ConfigIssue] = []

    # 1. Check for conflicting configurations
    if config.enable_artifacts and config.artifacts_output_path is None:
        issues.append(
            ConfigIssue(
                level="warning",
                message="enable_artifacts=True but artifacts_output_path not set (will use default path)",
                field="artifacts_output_path",
                suggestion="Explicitly set artifacts_output_path for production use",
            )
        )

    # 2. Check for dangerous configurations
    if config.recursion_limit > 200:
        issues.append(
            ConfigIssue(
                level="warning",
                message=f"High recursion_limit ({config.recursion_limit}) may cause stack overflow",
                field="recursion_limit",
                suggestion="Consider reducing to <= 200 for stability",
            )
        )

    if config.timeout_seconds is not None and config.timeout_seconds > 3600:
        issues.append(
            ConfigIssue(
                level="warning",
                message=f"Very long timeout ({config.timeout_seconds}s) may cause hangs",
                field="timeout_seconds",
                suggestion="Consider reducing to <= 3600s (1 hour)",
            )
        )

    # 3. Check for missing dependencies (MCP configs)
    if config.mcp_configs:
        for i, mcp_cfg in enumerate(config.mcp_configs):
            if not hasattr(mcp_cfg, "name") or not mcp_cfg.name:
                issues.append(
                    ConfigIssue(
                        level="error",
                        message=f"MCP config [{i}] missing required 'name' field",
                        field=f"mcp_configs[{i}].name",
                        suggestion="Add name field to MCP configuration",
                    )
                )

    # 4. Check for performance concerns
    if config.llm.temperature is not None and config.llm.temperature > 1.0:
        issues.append(
            ConfigIssue(
                level="info",
                message=f"High temperature ({config.llm.temperature}) may reduce consistency",
                field="llm.temperature",
                suggestion="Consider using <= 1.0 for more deterministic output",
            )
        )

    if config.system_prompt and len(config.system_prompt) > 50_000:
        issues.append(
            ConfigIssue(
                level="warning",
                message=f"Large system_prompt ({len(config.system_prompt)} chars) consumes excessive tokens",
                field="system_prompt",
                suggestion="Consider reducing to < 50K characters for cost efficiency",
            )
        )

    # 5. Check for storage config issues
    if config.storage_config:
        if config.storage_config.backend_type not in ["local", "custom"]:
            issues.append(
                ConfigIssue(
                    level="error",
                    message=f"Invalid storage backend_type: {config.storage_config.backend_type}",
                    field="storage_config.backend_type",
                    suggestion="Use 'local' or 'custom'",
                )
            )

        if not config.storage_config.root_dir or not config.storage_config.root_dir.strip():
            issues.append(
                ConfigIssue(
                    level="error",
                    message="storage_config.root_dir cannot be empty",
                    field="storage_config.root_dir",
                    suggestion="Set a valid directory path",
                )
            )

    # 6. Check for planner config conflicts
    if config.planner_llm_config and not config.planner_config:
        issues.append(
            ConfigIssue(
                level="warning",
                message="planner_llm_config set but planner_config is None (Planner will not start)",
                field="planner_config",
                suggestion="Set planner_config or remove planner_llm_config",
            )
        )

    return issues


__all__ = [
    "ConfigIssue",
    "check_config_health",
]
