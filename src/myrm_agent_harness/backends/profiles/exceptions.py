"""Exceptions for Agent Profile Backend.

[INPUT]
(none)

[OUTPUT]
- ProfileNotFoundError: Raised when an agent profile is not found.
- ProfileAlreadyExistsError: Raised when creating a duplicate profile.

[POS]
Profile backend exception types.
"""


class ProfileNotFoundError(Exception):
    """Raised when an agent profile is not found."""


class ProfileAlreadyExistsError(Exception):
    """Raised when attempting to create a profile that already exists."""
