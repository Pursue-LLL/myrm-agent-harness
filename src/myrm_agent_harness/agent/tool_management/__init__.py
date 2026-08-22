"""Tool management subsystem — unified tool registration, dedup, ordering, and lifecycle.

Public API re-exported here for convenience.
"""

from .env_dependency import (
    DependencyKind,
    DependencyProbeResult,
    EnvDependencySpec,
    RequirementLevel,
    ToolEnvDependencyProfile,
    ToolEnvHealthReport,
    correlate_tool_surface_env_health,
    export_env_dependency_inventory,
    get_tool_env_dependencies,
    get_tools_requiring_dependency,
    probe_tool_env_health,
)
from .lifecycle_manager import ToolLifecycleManager
from .lifecycle_protocol import LifecycleAwareTool
from .registry import ToolRegistry
from .tool_catalog import (
    ToolCatalogRole,
    build_tool_catalog_row,
    get_tool_catalog_role,
    get_tool_env_profile,
    probe_tool_runtime_health,
)
from .tool_layers import ToolLayer, get_tool_layer, register_tool_layer, tool_layer_snapshot_label
from .types import ToolBindMode, ToolSnapshot, ToolSource
from .utils import with_dynamic_hints

__all__ = [
    "DependencyKind",
    "DependencyProbeResult",
    "EnvDependencySpec",
    "LifecycleAwareTool",
    "RequirementLevel",
    "ToolBindMode",
    "ToolCatalogRole",
    "ToolEnvDependencyProfile",
    "ToolEnvHealthReport",
    "ToolLayer",
    "ToolLifecycleManager",
    "ToolRegistry",
    "ToolSnapshot",
    "ToolSource",
    "build_tool_catalog_row",
    "correlate_tool_surface_env_health",
    "export_env_dependency_inventory",
    "get_tool_catalog_role",
    "get_tool_env_dependencies",
    "get_tool_env_profile",
    "get_tool_layer",
    "get_tools_requiring_dependency",
    "probe_tool_env_health",
    "probe_tool_runtime_health",
    "register_tool_layer",
    "tool_layer_snapshot_label",
    "with_dynamic_hints",
]
