"""Stable import-path facade for ``toolkits.memory.mcp_server``.

[POS]
Re-exports the canonical implementation from ``agent_surface/mcp_server.py``.

[INPUT]
- myrm_agent_harness.toolkits.memory.agent_surface.mcp_server (canonical implementation)

[OUTPUT]
- Module-level re-exports of every public name in the canonical module
"""

from myrm_agent_harness.toolkits.memory.agent_surface import mcp_server as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _impl, _name, _value
