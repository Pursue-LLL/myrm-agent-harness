"""Ephemeral and read-only memory managers for subagent isolation.

Provides two isolation strategies:
- EphemeralMemoryManager: reads from parent, writes to a local dict (no DB pollution).
- ReadOnlyMemoryView: reads from parent, all writes raise PermissionError.

[INPUT]
- toolkits.memory.ephemeral.dict_backed_manager::EphemeralMemoryManager (POS: Ephemeral memory isolation strategy for subagents.)
- toolkits.memory.ephemeral.read_only_view::ReadOnlyMemoryView (POS: Read-only memory isolation strategy for subagents.)

[OUTPUT]
- EphemeralMemoryManager: Dict-backed ephemeral memory manager.
- ReadOnlyMemoryView: Read-only proxy over a parent MemoryManager.

[POS]
Ephemeral and read-only memory managers for subagent isolation.
"""

from myrm_agent_harness.toolkits.memory.ephemeral.dict_backed_manager import EphemeralMemoryManager
from myrm_agent_harness.toolkits.memory.ephemeral.read_only_view import ReadOnlyMemoryView

__all__ = ["EphemeralMemoryManager", "ReadOnlyMemoryView"]
