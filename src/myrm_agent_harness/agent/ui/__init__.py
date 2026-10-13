"""Transport-Agnostic Extension UI Sub-Protocol Module.

[INPUT]
- ui_types, base_ui_context, headless_ui_context, reverse_push_ui_context from .

[OUTPUT]
- ExtensionUIContext, HeadlessUIContext, ReversePushUIContext, PushSink
- UIRequest, UIResponse, UISelectOption, UIRequestType, UINotifyLevel
- ExtensionUIError, ExtensionUITimeoutError, ExtensionUICancelledError

[POS]
Facade entry point for the transport-agnostic Extension UI context subsystem.
"""

from __future__ import annotations

from .base_ui_context import ExtensionUIContext
from .headless_ui_context import HeadlessUIContext
from .reverse_push_ui_context import PushSink, ReversePushUIContext
from .ui_types import (
    ExtensionUICancelledError,
    ExtensionUIError,
    ExtensionUITimeoutError,
    UINotifyLevel,
    UIRequest,
    UIRequestType,
    UIResponse,
    UISelectOption,
)

__all__ = [
    "ExtensionUIContext",
    "HeadlessUIContext",
    "ReversePushUIContext",
    "PushSink",
    "UIRequest",
    "UIResponse",
    "UISelectOption",
    "UIRequestType",
    "UINotifyLevel",
    "ExtensionUIError",
    "ExtensionUITimeoutError",
    "ExtensionUICancelledError",
]
