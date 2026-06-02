"""Context management configuration.

Centralized configuration for context file lifecycle management:
- Cleanup thresholds
- Storage quotas
- Session-aware cleanup rules

[INPUT]
- (none)

[OUTPUT]
- ContextCleanupConfig: Configuration for context file cleanup.
- StorageQuotaConfig: Configuration for storage quota management.
- get_cleanup_config: Get or create global cleanup configuration singleton.
- set_cleanup_config: Inject custom cleanup configuration.
- get_quota_config: Get or create global quota configuration singleton.

[POS]
Context management configuration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextCleanupConfig:
    """Configuration for context file cleanup.

    Smart cleanup rules:
    1. If session active within session_active_days → keep all files
    2. Else if file accessed within file_access_days → keep file
    3. Else → remove file

    Attributes:
        max_age_days: Fallback max age when session info unavailable
        session_active_days: Keep files if session active within this period
        file_access_days: Keep files if accessed within this period
        batch_size: Process sessions in batches (for large-scale scenarios)
        timeout_seconds: Maximum cleanup execution time
    """

    max_age_days: int = 7
    session_active_days: int = 30
    file_access_days: int = 14
    batch_size: int = 100
    timeout_seconds: float = 1800.0  # 30 minutes

    def __post_init__(self) -> None:
        """Validate configuration values."""
        errors: list[str] = []

        if self.max_age_days <= 0:
            errors.append(f"max_age_days must be positive, got {self.max_age_days}")

        if self.session_active_days <= 0:
            errors.append(f"session_active_days must be positive, got {self.session_active_days}")

        if self.file_access_days <= 0:
            errors.append(f"file_access_days must be positive, got {self.file_access_days}")

        if self.session_active_days < self.file_access_days:
            errors.append(
                f"session_active_days ({self.session_active_days}) should be >= "
                f"file_access_days ({self.file_access_days}) for consistent cleanup behavior"
            )

        if self.file_access_days < self.max_age_days:
            errors.append(
                f"file_access_days ({self.file_access_days}) should be >= "
                f"max_age_days ({self.max_age_days}) for graceful degradation"
            )

        if self.batch_size <= 0:
            errors.append(f"batch_size must be positive, got {self.batch_size}")

        if self.timeout_seconds <= 0:
            errors.append(f"timeout_seconds must be positive, got {self.timeout_seconds}")

        if errors:
            raise ValueError(f"Invalid ContextCleanupConfig: {'; '.join(errors)}")


@dataclass
class StorageQuotaConfig:
    """Configuration for storage quota management.

    Attributes:
        enabled: Enable quota management (default: False for local, True for cloud)
        per_session_limit_mb: Storage limit per session in MB
        auto_cleanup_threshold: Trigger cleanup at this usage ratio (0.0-1.0)
    """

    enabled: bool = False
    per_session_limit_mb: int = 500
    auto_cleanup_threshold: float = 0.8

    def __post_init__(self) -> None:
        """Validate configuration values."""
        errors: list[str] = []

        if self.per_session_limit_mb <= 0:
            errors.append(f"per_session_limit_mb must be positive, got {self.per_session_limit_mb}")

        if not 0.0 < self.auto_cleanup_threshold < 1.0:
            errors.append(f"auto_cleanup_threshold must be in (0, 1), got {self.auto_cleanup_threshold}")

        if errors:
            raise ValueError(f"Invalid StorageQuotaConfig: {'; '.join(errors)}")

    @property
    def per_session_limit_bytes(self) -> int:
        """Get per-session limit in bytes."""
        return self.per_session_limit_mb * 1024 * 1024


# Global configuration instances (lazily loaded)
_cleanup_config: ContextCleanupConfig | None = None
_quota_config: StorageQuotaConfig | None = None


def get_cleanup_config() -> ContextCleanupConfig:
    """Get or create global cleanup configuration singleton."""
    global _cleanup_config
    if _cleanup_config is None:
        _cleanup_config = ContextCleanupConfig()
    return _cleanup_config


def set_cleanup_config(config: ContextCleanupConfig) -> None:
    """Inject custom cleanup configuration."""
    global _cleanup_config
    _cleanup_config = config


def get_quota_config() -> StorageQuotaConfig:
    """Get or create global quota configuration singleton."""
    global _quota_config
    if _quota_config is None:
        _quota_config = StorageQuotaConfig()
    return _quota_config


def set_quota_config(config: StorageQuotaConfig) -> None:
    """Inject custom quota configuration."""
    global _quota_config
    _quota_config = config


def reset_config() -> None:
    """Reset global configuration (for testing)."""
    global _cleanup_config, _quota_config
    _cleanup_config = None
    _quota_config = None
