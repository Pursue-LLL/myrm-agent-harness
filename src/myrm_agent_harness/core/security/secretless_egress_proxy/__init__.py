"""Secretless Credential Egress Proxy and Placeholder Swap Suite."""

from __future__ import annotations

from .placeholder_registry import PlaceholderRegistry
from .swap_on_access_proxy import SwapOnAccessProxy
from .types import (
    BoundCredentialSpec,
    ProxyInspectionResult,
    SwapEvent,
)

__all__ = [
    "BoundCredentialSpec",
    "PlaceholderRegistry",
    "ProxyInspectionResult",
    "SwapEvent",
    "SwapOnAccessProxy",
]
