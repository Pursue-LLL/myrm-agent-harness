"""Compatibility facade for ``toolkits.memory.memory_agent_tools``.

[POS]
Stable import-path shim. Re-exports the canonical implementation from
``agent_surface/memory_agent_tools.py`` so legacy callers keep working unchanged.

[INPUT]
- myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools (canonical implementation)

[OUTPUT]
- Module-level re-exports of every public name in the canonical module
"""

from myrm_agent_harness.toolkits.memory.agent_surface import memory_agent_tools as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _impl, _name, _value
