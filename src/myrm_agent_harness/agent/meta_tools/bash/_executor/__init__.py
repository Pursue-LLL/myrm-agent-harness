"""Bash executor domain: aggregate root, mixins, and session management.

Public symbols: :class:`BashExecutor`, :class:`BashExecutionError`.
See _ARCH.md for file index.
"""

from .executor import BashExecutionError, BashExecutor

__all__ = ["BashExecutionError", "BashExecutor"]
