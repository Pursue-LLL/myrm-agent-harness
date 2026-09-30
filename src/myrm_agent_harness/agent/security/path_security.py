"""Path security — re-exported from core.security.path.

[INPUT]
- core.security.path (POS: Path security domain — pattern engine, filesystem safety, protection rules.)

[OUTPUT]
- agent.security.path_security: Stable `agent.security.*` alias for the core path-security API.

[POS]
Import-path shim. Holds no logic; `core.security.path.__all__` defines
exactly what this module re-exports, so the alias never widens the public API.
"""

from myrm_agent_harness.core.security.path import *  # noqa: F403
