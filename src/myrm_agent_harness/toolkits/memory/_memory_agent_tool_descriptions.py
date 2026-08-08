"""Compatibility facade for ``toolkits.memory._memory_agent_tool_descriptions``.

Implementation lives in ``agent_surface/_memory_agent_tool_descriptions.py``. Keep this import path stable.
"""

from myrm_agent_harness.toolkits.memory.agent_surface import _memory_agent_tool_descriptions as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _impl, _name, _value
