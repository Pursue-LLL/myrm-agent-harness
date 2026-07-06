"""Tool management subsystem — unified tool registration, dedup, ordering, and lifecycle.

Public API re-exported here for convenience.
"""

from .lifecycle_manager import ToolLifecycleManager
from .lifecycle_protocol import LifecycleAwareTool
from .registry import ToolRegistry
from .tool_catalog import ToolCatalogRole, build_tool_catalog_row, get_tool_catalog_role
from .tool_layers import ToolLayer, get_tool_layer, register_tool_layer
from .types import ToolBindMode, ToolEntry, ToolSnapshot, ToolSource
from .utils import with_dynamic_hints

__all__ = [
    "LifecycleAwareTool",
    "ToolBindMode",
    "ToolCatalogRole",
    "ToolLayer",
    "ToolLifecycleManager",
    "ToolRegistry",
    "ToolSnapshot",
    "ToolSource",
    "build_tool_catalog_row",
    "get_tool_catalog_role",
    "get_tool_layer",
    "register_tool_layer",
    "with_dynamic_hints",
]
