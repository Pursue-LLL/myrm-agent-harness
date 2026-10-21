"""Abstract Base Extension UI Context Contract.

[INPUT]
- ui_types from .ui_types

[OUTPUT]
- ExtensionUIContext (Abstract base class)

[POS]
Abstract contract for transport-agnostic Extension UI context.
Allows skills, tools, and workflows to invoke UI interactions regardless of transport (WebUI, RPC, Headless).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from .ui_types import UINotifyLevel, UISelectOption


class ExtensionUIContext(ABC):
    """Abstract interface exposing transport-agnostic interactive UI primitives."""

    @abstractmethod
    async def select(
        self,
        title: str,
        options: Sequence[UISelectOption],
        default: str | None = None,
        timeout_s: float = 60.0,
    ) -> str:
        """Prompt user to select one option from a list."""

    @abstractmethod
    async def confirm(
        self,
        title: str,
        message: str,
        default: bool = False,
        timeout_s: float = 60.0,
    ) -> bool:
        """Prompt user with a confirmation dialog (Yes / No)."""

    @abstractmethod
    async def input(
        self,
        title: str,
        placeholder: str = "",
        default: str = "",
        timeout_s: float = 60.0,
    ) -> str:
        """Prompt user with a single-line or multi-line text input field."""

    @abstractmethod
    async def editor(
        self,
        title: str,
        content: str,
        language: str = "text",
        timeout_s: float = 300.0,
    ) -> str:
        """Open a code / text editor for the user to view and edit content."""

    @abstractmethod
    async def notify(
        self,
        message: str,
        level: UINotifyLevel = "info",
    ) -> None:
        """Display an asynchronous notification / toast to the user."""
