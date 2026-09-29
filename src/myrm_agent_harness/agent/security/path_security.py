"""Path security — re-exported from core.security.path_security.

[INPUT]
- core.security.path_security (POS: Path security — single source of truth for dangerous paths and sensitive files.)

[OUTPUT]
- agent.security.path_security: Stable `agent.security.*` alias for the core path-security API.

[POS]
Import-path shim. Holds no logic; `core.security.path_security.__all__` defines
exactly what this module re-exports, so the alias never widens the public API.
"""

from myrm_agent_harness.core.security.path_security import *  # noqa: F403
from myrm_agent_harness.core.security.path_security import (
    _build_dangerous_paths as _build_dangerous_paths,
)
