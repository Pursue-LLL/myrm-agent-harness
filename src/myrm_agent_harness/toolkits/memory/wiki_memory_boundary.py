"""Compatibility facade for ``toolkits.memory.wiki_memory_boundary``.

Implementation lives in ``agent_surface/wiki_memory_boundary.py``. Keep this import path stable.
"""

from myrm_agent_harness.toolkits.memory.agent_surface import wiki_memory_boundary as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _impl, _name, _value
