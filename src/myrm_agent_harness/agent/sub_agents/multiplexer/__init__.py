"""Persistent Agent Session Multiplexer and cross-agent inspect/instruct public API.

[INPUT]
- types::(
    AgentInstruction, InspectSnapshot, InstructResult, MultiplexerSession, MultiplexerSessionState
  )
- session_multiplexer::(AgentSessionMultiplexer, get_session_multiplexer)
- inspect_instruct_tools::(create_inspect_agent_session_tool, create_instruct_agent_tool)

[OUTPUT]
- __all__: Exported public symbols for agent multiplexing and cross-agent coordination.

[POS]
Harness sub-package facade for tmux-style agent session multiplexing.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.multiplexer.inspect_instruct_tools import (
    create_inspect_agent_session_tool,
    create_instruct_agent_tool,
)
from myrm_agent_harness.agent.sub_agents.multiplexer.session_multiplexer import (
    AgentSessionMultiplexer,
    get_session_multiplexer,
)
from myrm_agent_harness.agent.sub_agents.multiplexer.types import (
    AgentInstruction,
    InspectSnapshot,
    InstructResult,
    MultiplexerSession,
    MultiplexerSessionState,
)

__all__ = [
    "AgentInstruction",
    "AgentSessionMultiplexer",
    "InspectSnapshot",
    "InstructResult",
    "MultiplexerSession",
    "MultiplexerSessionState",
    "create_inspect_agent_session_tool",
    "create_instruct_agent_tool",
    "get_session_multiplexer",
]
