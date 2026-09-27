"""Public subagent helpers for server-layer delegation wiring.

[POS]
Stable api/ re-export surface for ``build_parent_delegatable_toolkit`` and the
shared subagent checkpointer (HITL approval / interrupt resume).

- ``get_subagent_checkpointer`` — process-wide shared checkpointer so
  GraphInterrupt approvals survive child runs and resume restores the thread.
- ``close_subagent_checkpointer`` — releases underlying storage connections safely.
- ``reset_subagent_checkpointer`` — resets checkpointer singleton for test isolation.
- ``delete_subagent_checkpoint`` — drops a finished subagent thread (hygiene)
  once a run reaches a terminal (non-approval) status.
"""

from myrm_agent_harness.agent.sub_agents.builder import build_parent_delegatable_toolkit
from myrm_agent_harness.agent.sub_agents.checkpointer import (
    close_subagent_checkpointer,
    delete_subagent_checkpoint,
    get_subagent_checkpointer,
    reset_subagent_checkpointer,
)

__all__ = [
    "build_parent_delegatable_toolkit",
    "close_subagent_checkpointer",
    "delete_subagent_checkpoint",
    "get_subagent_checkpointer",
    "reset_subagent_checkpointer",
]
