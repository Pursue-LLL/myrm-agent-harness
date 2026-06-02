"""Subagent configuration registry and loading utilities.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .types::SubagentConfig (POS: Subagent 声明式配置数据类)
- .config_loader::load_subagent_configs_from_directory (POS: 从目录加载YAML配置文件)

[OUTPUT]
- SUBAGENT_CONFIGS: 全局 subagent 配置注册表
- register_subagent_configs(): 注册 subagent 配置到全局注册表
- register_subagent_configs_from_directory(): 从目录加载并注册配置
- auto_register_subagent_configs(): 自动注册标准目录结构的配置

[POS]
Subagent configuration registry and loader. Provides a global config registry with convenient loading functions.

"""

from __future__ import annotations

from .types import SubagentConfig

# ---------------------------------------------------------------------------
# Global Registry
# ---------------------------------------------------------------------------

SUBAGENT_CONFIGS: dict[str, SubagentConfig] = {}
"""[DEPRECATED] Registry of subagent configurations.
Use SubagentCatalog protocol instead."""


# ---------------------------------------------------------------------------
# Registration Functions
# ---------------------------------------------------------------------------


def register_subagent_configs(configs: dict[str, SubagentConfig]) -> None:
    """Register subagent configurations into the global registry.

    Business layer should call this at application startup.
    Overwrites existing entries with the same key.

    Note: This function accepts pre-built SubagentConfig instances.
    For loading from YAML files, use ``register_subagent_configs_from_directory()``.
    """
    SUBAGENT_CONFIGS.update(configs)


def register_subagent_configs_from_directory(dir_path: str, pattern: str = "*.yaml") -> dict[str, SubagentConfig]:
    """Load and register subagent configurations from a directory of YAML files.

    Args:
        dir_path: Directory containing YAML configuration files
        pattern: Glob pattern for config files (default "*.yaml")

    Returns:
        Dictionary of successfully loaded configurations (also registered to SUBAGENT_CONFIGS)

    Example:
        >>> register_subagent_configs_from_directory("configs/subagents/core")
        {'search': SubagentConfig(...), 'browser': SubagentConfig(...)}
    """
    from .config_loader import load_subagent_configs_from_directory

    configs = load_subagent_configs_from_directory(dir_path, pattern)
    SUBAGENT_CONFIGS.update(configs)
    return configs


def auto_register_subagent_configs(
    base_path: str | None = None, load_core: bool = True, load_custom: bool = True
) -> dict[str, SubagentConfig]:
    """Automatically register subagent configs from standard directory structure.

    Loads configurations with priority: custom > core (custom configs override core).

    Args:
        base_path: Base directory containing subagents/ folder (required).
            Must be explicitly provided by the business layer.
        load_core: Whether to load core configs from core/ subdirectory
        load_custom: Whether to load custom configs from custom/ subdirectory

    Returns:
        Dictionary of all loaded configurations

    Raises:
        ValueError: If base_path is None. Framework layer requires explicit path from business layer.

    Example Directory Structure:
        configs/subagents/
          ├── core/       # Framework-provided configs
          │   ├── search.yaml
          │   └── browser.yaml
          └── custom/     # User-defined configs
              └── my_agent.yaml

    Example Usage:
        >>> from pathlib import Path
        >>> config_dir = Path(__file__).parent / "configs" / "subagents"
        >>> configs = auto_register_subagent_configs(base_path=str(config_dir))
    """
    from pathlib import Path

    if base_path is None:
        raise ValueError(
            "base_path is required. Framework layer does not auto-detect paths. "
            "Business layer must explicitly provide the configuration directory path."
        )

    base_path = Path(base_path)

    all_configs: dict[str, SubagentConfig] = {}

    # Load core configs first (lower priority)
    if load_core:
        core_path = base_path / "core"
        if core_path.exists():
            core_configs = register_subagent_configs_from_directory(str(core_path))
            all_configs.update(core_configs)

    # Load custom configs (higher priority, can override core)
    if load_custom:
        custom_path = base_path / "custom"
        if custom_path.exists():
            custom_configs = register_subagent_configs_from_directory(str(custom_path))
            all_configs.update(custom_configs)

    return all_configs
