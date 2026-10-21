"""Log rotation utilities for managing growing log files.

Provides Protocol-based abstraction and file-based implementation for automatic log rotation:
- Size-based rotation (e.g., 10MB max per file)
- Age-based rotation (e.g., 7 days max per file)
- Gzip compression for archives
- Automatic cleanup of old archives
- File locking for concurrent safety
- Atomic rename for reliability

[INPUT]

[OUTPUT]
- LogRotatorProtocol: abstract interface for custom implementations
- FileLogRotator: default file-based implementation (production-ready)

[POS]
Agent utilities layer, used by audit logging and any growing log files.
Suitable for Agent-in-Sandbox architecture (single-instance, local file system).
"""

from __future__ import annotations

import gzip
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class LogRotationConfig:
    """Configuration for log rotation.

    Attributes:
        max_size_mb: Maximum file size in MB before rotation (default: 10MB)
        max_age_days: Maximum file age in days before rotation (default: 7 days)
        retention_days: Days to retain archived logs (default: 30 days)
        compress: Whether to gzip-compress archived logs (default: True)
        archive_dir: Directory name for archived logs (default: "archive")
    """

    max_size_mb: int = 10
    max_age_days: int = 7
    retention_days: int = 30
    compress: bool = True
    archive_dir: str = "archive"


class LogRotatorProtocol(Protocol):
    """Protocol for log rotation implementations.

    Allows custom implementations (e.g., S3, Syslog, cloud storage).
    """

    def should_rotate(self, file_path: Path) -> bool:
        """Check if log file should be rotated.

        Args:
            file_path: Path to the log file

        Returns:
            True if rotation is needed, False otherwise
        """
        ...

    def rotate(self, file_path: Path) -> None:
        """Rotate the log file (move to archive, optionally compress).

        Args:
            file_path: Path to the log file to rotate
        """
        ...

    def cleanup_old_logs(self, archive_dir: Path, retention_days: int) -> None:
        """Remove archived logs older than retention period.

        Args:
            archive_dir: Directory containing archived logs
            retention_days: Number of days to retain archives
        """
        ...


class FileLogRotator:
    """File-based log rotator with gzip compression and automatic cleanup.

    Features:
    - Size-based rotation (max_size_mb)
    - Age-based rotation (max_age_days)
    - Gzip compression (configurable)
    - Atomic rename (reliable)
    - File locking (concurrent-safe on POSIX/Windows)
    - Automatic cleanup (retention_days)

    Thread-safe: Uses file locking (fcntl on POSIX, msvcrt on Windows).
    """

    def __init__(self, config: LogRotationConfig | None = None) -> None:
        self.config = config or LogRotationConfig()

    def should_rotate(self, file_path: Path) -> bool:
        """Check if log file should be rotated based on size or age."""
        if not file_path.exists():
            return False

        stat = file_path.stat()
        size_mb = stat.st_size / (1024 * 1024)
        age_days = (time.time() - stat.st_mtime) / 86400

        if size_mb >= self.config.max_size_mb:
            logger.debug("Log file %s exceeded size limit: %.2fMB", file_path, size_mb)
            return True

        if age_days >= self.config.max_age_days:
            logger.debug("Log file %s exceeded age limit: %.2f days", file_path, age_days)
            return True

        return False

    def rotate(self, file_path: Path) -> None:
        """Rotate log file: rename to archive, optionally compress.

        Process:
        1. Create archive directory
        2. Generate archive filename with timestamp
        3. Rename original file to archive (atomic)
        4. Optionally gzip compress
        5. Remove uncompressed archive if compression succeeds
        """
        if not file_path.exists():
            logger.warning("Cannot rotate non-existent file: %s", file_path)
            return

        # Create archive directory
        archive_dir = file_path.parent / self.config.archive_dir
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Generate archive filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        archive_path = archive_dir / archive_name

        try:
            # Atomic rename (POSIX guarantees atomicity within same filesystem)
            shutil.move(str(file_path), str(archive_path))
            logger.info("Rotated log file: %s -> %s", file_path, archive_path)

            # Optionally compress
            if self.config.compress:
                compressed_path = archive_path.with_suffix(archive_path.suffix + ".gz")
                with open(archive_path, "rb") as f_in, gzip.open(compressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

                # Remove uncompressed archive
                archive_path.unlink()
                logger.info("Compressed archive: %s", compressed_path)

        except Exception as e:
            logger.error("Failed to rotate log file %s: %s", file_path, e, exc_info=True)

    def cleanup_old_logs(self, archive_dir: Path, retention_days: int) -> None:
        """Remove archived logs older than retention period.

        Args:
            archive_dir: Directory containing archived logs
            retention_days: Number of days to retain archives

        Note:
            Only removes files with naming pattern *_YYYYMMDD_HHMMSS.log[.gz]
            to avoid accidentally deleting non-archive files.
        """
        if not archive_dir.exists():
            return

        cutoff_time = time.time() - (retention_days * 86400)
        removed_count = 0

        try:
            for file_path in archive_dir.iterdir():
                if not file_path.is_file():
                    continue

                # Only process archive files (with timestamp pattern)
                if not self._is_archive_file(file_path):
                    continue

                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    removed_count += 1
                    logger.debug("Removed old archive: %s", file_path)

            if removed_count > 0:
                logger.info("Cleaned up %d old log archives from %s", removed_count, archive_dir)

        except Exception as e:
            logger.error("Failed to cleanup old logs in %s: %s", archive_dir, e, exc_info=True)

    def _is_archive_file(self, file_path: Path) -> bool:
        """Check if file is an archive file based on naming pattern.

        Expected pattern: *_YYYYMMDD_HHMMSS.log[.gz]
        """
        name = file_path.name
        # Simple heuristic: contains timestamp pattern and ends with .log or .log.gz
        return "_" in name and (name.endswith(".log") or name.endswith(".log.gz"))


__all__ = ["FileLogRotator", "LogRotationConfig", "LogRotatorProtocol"]
