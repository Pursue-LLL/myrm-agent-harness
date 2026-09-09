"""Agent meta-tools for user interaction.

[OUTPUT]
- ClientSurface, resolve_client_surface, supports_inline_interactive_ui: Client capability probes.

[POS]
Public exports for client capability resolution.
"""

from myrm_agent_harness.agent.meta_tools.interaction.inline_ui_capability import (
    ClientSurface,
    resolve_client_surface,
    supports_inline_interactive_ui,
)

__all__ = [
    "ClientSurface",
    "resolve_client_surface",
    "supports_inline_interactive_ui",
]

