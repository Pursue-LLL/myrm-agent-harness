"""Event log backends — built-in storage implementations."""

from .file_backend import FileEventLogBackend

__all__ = ["FileEventLogBackend"]
