"""Mock implementations for testing.

This module provides in-memory implementations of backend protocols,
useful for testing without external dependencies.
"""

from .skill_backend import InMemorySkillBackend
from .storage_backend import InMemoryStorageBackend

__all__ = [
    "InMemorySkillBackend",
    "InMemoryStorageBackend",
]
