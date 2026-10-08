"""Directory trust gate types and data structures.

[INPUT]
- Untrusted repository configuration extraction payloads.

[OUTPUT]
- TrustStatus, ProjectRemoteConfig, GatedRemoteConfig.

[POS]
Domain value objects modeling directory trust evaluation boundaries.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class TrustStatus(StrEnum):
    """Trust status of a directory."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class ProjectRemoteConfig:
    """Project remote configuration extracted from local repository files.

    Attributes:
        remote_url: Remote host endpoint (e.g. cloud sync endpoint or API host).
        remote_token: Authentication token accompanying the remote endpoint.
        scope: Logical isolation scope or workspace name (harmless, purely local).
        extra_settings: Additional non-sensitive key-value settings.
    """

    remote_url: str | None = None
    remote_token: str | None = None
    scope: str | None = None
    extra_settings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GatedRemoteConfig:
    """Sanitized and gated project configuration.

    Attributes:
        sanitized_directory: Absolute normalized directory path.
        is_trusted: Whether directory is explicitly trusted.
        is_remote_allowed: Whether remote dial/sync is permitted.
        allowed_remote_url: Permitted remote URL (None if untrusted).
        allowed_remote_token: Permitted remote token (None if untrusted).
        effective_scope: Effective project scope (retained even if untrusted).
        warning_message: Security warning if remote credentials were dropped.
    """

    sanitized_directory: str
    is_trusted: bool
    is_remote_allowed: bool
    allowed_remote_url: str | None
    allowed_remote_token: str | None
    effective_scope: str | None
    warning_message: str | None = None
