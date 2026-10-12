# [POS] myrm-agent-harness/tests/toolkits/memory/test_facade_exports.py
# [INPUT] myrm_agent_harness.toolkits.memory (facade `__all__`)
# [OUTPUT] Regression gate: every name the memory facade advertises is actually provided

"""The memory facade must provide every name it lists in `__all__`.

A name that is listed but never imported makes
`from myrm_agent_harness.toolkits.memory import *` raise AttributeError.
"""

from __future__ import annotations

import myrm_agent_harness.toolkits.memory as memory_facade


def test_every_exported_name_resolves() -> None:
    unresolved = sorted(name for name in set(memory_facade.__all__) if not hasattr(memory_facade, name))
    assert not unresolved, f"`__all__` lists names the facade does not provide: {unresolved}"
