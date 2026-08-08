"""Compatibility facade for ``toolkits.memory.memory_search_policy``.

Implementation lives in ``agent_surface/memory_search_policy.py``. Keep this import path stable.
"""

from myrm_agent_harness.toolkits.memory.agent_surface import memory_search_policy as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _impl, _name, _value
