"""UI Types for Transport-Agnostic Extension UI Sub-Protocol.

[INPUT]
- None (standard library dataclasses & typing)

[OUTPUT]
- UIRequestType, UISelectOption, UIRequest, UIResponse, ExtensionUIError

[POS]
Data contract for transport-agnostic ExtensionUIContext and reverse push subprotocol.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

UIRequestType = Literal["select", "confirm", "input", "editor", "notify"]
UINotifyLevel = Literal["info", "warning", "error"]


class ExtensionUIError(Exception):
    """Base exception for Extension UI operations."""


class ExtensionUITimeoutError(ExtensionUIError):
    """Raised when user interaction timed out."""


class ExtensionUICancelledError(ExtensionUIError):
    """Raised when user cancelled the interaction."""


@dataclass(frozen=True)
class UISelectOption:
    """Option for ui.select interactive dropdown / list."""

    label: str
    value: str
    description: str | None = None


@dataclass(frozen=True)
class UIRequest:
    """Standard reverse push request frame sent to client."""

    request_id: str
    request_type: UIRequestType
    title: str
    message: str | None = None
    options: tuple[UISelectOption, ...] | None = None
    placeholder: str | None = None
    default_value: str | bool | None = None
    content: str | None = None
    language: str | None = None
    timeout_s: float = 60.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float | bool | list[dict[str, str | None]] | None]:
        """Serialize to wire format."""
        options_data = (
            [
                {
                    "label": opt.label,
                    "value": opt.value,
                    "description": opt.description,
                }
                for opt in self.options
            ]
            if self.options is not None
            else None
        )
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "title": self.title,
            "message": self.message,
            "options": options_data,
            "placeholder": self.placeholder,
            "default_value": self.default_value,
            "content": self.content,
            "language": self.language,
            "timeout_s": self.timeout_s,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class UIResponse:
    """Response frame received from client or fallback handler."""

    request_id: str
    value: str | bool | None = None
    cancelled: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        """Serialize to wire format."""
        return {
            "request_id": self.request_id,
            "value": self.value,
            "cancelled": self.cancelled,
            "error": self.error,
        }
