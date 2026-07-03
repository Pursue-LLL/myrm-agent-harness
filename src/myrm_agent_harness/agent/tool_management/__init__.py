"""Tool management subsystem — unified tool registration, dedup, ordering, and lifecycle.

Public API re-exported here for convenience.
"""

from .lifecycle_manager import ToolLifecycleManager
from .lifecycle_protocol import LifecycleAwareTool
from .registry import ToolRegistry
from .tool_layers import ToolLayer, get_tool_layer, register_tool_layer
from .types import ToolBindMode, ToolEntry, ToolSnapshot, ToolSource
from .utils import with_dynamic_hints

__all__ = [
    "LifecycleAwareTool",
    "ToolBindMode",
    "ToolLayer",
    "ToolLifecycleManager",
    "ToolRegistry",
    "ToolSnapshot",
    "ToolSource",
    "get_tool_layer",
    "register_tool_layer",
    "with_dynamic_hints",
]
