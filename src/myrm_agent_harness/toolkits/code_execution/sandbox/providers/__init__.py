"""Built-in sandbox providers.

- null.py:           NullProvider           — no-op passthrough (containers / disable mode)
- bwrap.py:          BwrapProvider          — Linux bubblewrap namespace isolation
- seatbelt.py:       SeatbeltProvider       — macOS sandbox-exec / Seatbelt profile
- appcontainer.py:   AppContainerProvider   — Windows AppContainer native isolation
"""

from myrm_agent_harness.toolkits.code_execution.sandbox.providers.bwrap import (
    BwrapProvider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import (
    NullProvider,
)
from myrm_agent_harness.toolkits.code_execution.sandbox.providers.seatbelt import (
    SeatbeltProvider,
)

__all__ = ["AppContainerProvider", "BwrapProvider", "NullProvider", "SeatbeltProvider"]


def __getattr__(name: str):
    if name == "AppContainerProvider":
        from myrm_agent_harness.toolkits.code_execution.sandbox.providers.appcontainer import (
            AppContainerProvider,
        )

        return AppContainerProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
