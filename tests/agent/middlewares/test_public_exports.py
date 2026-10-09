"""Every name advertised by ``agent.middlewares.__all__`` must resolve.

[INPUT]
- myrm_agent_harness.agent.middlewares: the public middleware facade

[OUTPUT]
- Regression guard for facades that re-export names whose definitions are missing.

[POS]
Unit tests mirroring src/myrm_agent_harness/agent/middlewares/__init__.py.
"""

from __future__ import annotations

import myrm_agent_harness.agent.middlewares as middlewares


def test_every_advertised_name_resolves() -> None:
    missing = [name for name in middlewares.__all__ if not hasattr(middlewares, name)]
    assert missing == []
