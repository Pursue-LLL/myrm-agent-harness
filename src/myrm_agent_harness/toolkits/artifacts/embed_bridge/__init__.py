"""Embed Bridge & Host Context Injection Subpackage.

Exports:
- WidgetDisplayMode
- HostContextSnapshot
- HostBridgeMessage
- EmbedSecurityPolicy
- BridgeInjectedContext
- HostContextBridgeEngine

[INPUT]
- bridge_engine
- models

[OUTPUT]
- (模块级副作用与注册)

[POS]
Embed Bridge & Host Context Injection Subpackage.
"""

from .bridge_engine import HostContextBridgeEngine
from .models import (
    BridgeInjectedContext,
    EmbedSecurityPolicy,
    HostBridgeMessage,
    HostContextSnapshot,
    WidgetDisplayMode,
)

__all__ = [
    "WidgetDisplayMode",
    "HostContextSnapshot",
    "HostBridgeMessage",
    "EmbedSecurityPolicy",
    "BridgeInjectedContext",
    "HostContextBridgeEngine",
]
