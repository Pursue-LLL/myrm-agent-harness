"""Stable import-path facade for ``toolkits.memory.wiki_memory_boundary``.

[POS]
Re-exports the canonical implementation from ``agent_surface/wiki_memory_boundary.py``.

[INPUT]
- myrm_agent_harness.toolkits.memory.agent_surface.wiki_memory_boundary (canonical implementation)

[OUTPUT]
- Module-level re-exports of every public name in the canonical module
"""

from myrm_agent_harness.toolkits.memory.agent_surface import (
    wiki_memory_boundary as _impl,
)

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _impl, _name, _value
