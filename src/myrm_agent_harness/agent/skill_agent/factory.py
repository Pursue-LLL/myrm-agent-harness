"""Agent factory facade — stable import path for create_skill_agent.

[INPUT]
- agent._factory.builder::create_skill_agent (POS: SkillAgent assembly pipeline)

[OUTPUT]
- create_skill_agent(): public factory entry (re-export)

[POS]
Stable import path for agent package, client.py, and api/factory.py. Delegates to agent._factory.
MCP routing internals live in agent._factory.mcp_routing (tests import from there directly).
"""

from myrm_agent_harness.agent._factory.builder import create_skill_agent

__all__ = ["create_skill_agent"]
