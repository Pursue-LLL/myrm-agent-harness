"""Checkpoint metrics data structures.

Provides monitoring data structures for checkpoint save/resume operations.
Business layer can use these metrics for monitoring and alerting.

Design principle: Framework provides data structure, business layer decides monitoring solution.

[INPUT]
- (none)

[OUTPUT]
- CheckpointMetrics: Checkpoint operation metrics for monitoring and tuning.

[POS]
Checkpoint metrics data structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class CheckpointMetrics:
    """Checkpoint operation metrics.

    Tracks save/resume operations for monitoring and optimization.
    """

    # Save operations
    save_count: int = 0
    """Total number of checkpoint saves"""

    save_success_count: int = 0
    """Number of successful saves"""

    save_failure_count: int = 0
    """Number of failed saves"""

    save_total_ms: float = 0.0
    """Total time spent saving checkpoints (milliseconds)"""

    # Resume operations
    resume_count: int = 0
    """Total number of checkpoint resumes"""

    resume_success_count: int = 0
    """Number of successful resumes"""

    resume_failure_count: int = 0
    """Number of failed resumes"""

    resume_total_ms: float = 0.0
    """Total time spent resuming checkpoints (milliseconds)"""

    # Storage
    total_checkpoints: int = 0
    """Current number of stored checkpoints"""

    total_size_bytes: int = 0
    """Total size of all checkpoints (bytes)"""

    # Message extraction
    messages_extracted_count: int = 0
    """Number of times messages were successfully extracted"""

    messages_extraction_failures: int = 0
    """Number of times message extraction failed"""

    def to_dict(self) -> dict[str, float | int]:
        """Export metrics for business layer monitoring.

        Returns:
            Dict containing all metrics
        """
        return {
            # Save metrics
            "save_count": self.save_count,
            "save_success_count": self.save_success_count,
            "save_failure_count": self.save_failure_count,
            "save_success_rate": self.save_success_rate,
            "save_avg_ms": self.save_avg_ms,
            "save_total_ms": self.save_total_ms,
            # Resume metrics
            "resume_count": self.resume_count,
            "resume_success_count": self.resume_success_count,
            "resume_failure_count": self.resume_failure_count,
            "resume_success_rate": self.resume_success_rate,
            "resume_avg_ms": self.resume_avg_ms,
            "resume_total_ms": self.resume_total_ms,
            # Storage metrics
            "total_checkpoints": self.total_checkpoints,
            "total_size_bytes": self.total_size_bytes,
            "total_size_mb": self.total_size_mb,
            # Message extraction metrics
            "messages_extracted_count": self.messages_extracted_count,
            "messages_extraction_failures": self.messages_extraction_failures,
            "messages_extraction_success_rate": self.messages_extraction_success_rate,
        }

    @property
    def save_success_rate(self) -> float:
        """Calculate save success rate (0.0-1.0)."""
        if self.save_count == 0:
            return 0.0
        return self.save_success_count / self.save_count

    @property
    def save_avg_ms(self) -> float:
        """Calculate average save time in milliseconds."""
        if self.save_count == 0:
            return 0.0
        return self.save_total_ms / self.save_count

    @property
    def resume_success_rate(self) -> float:
        """Calculate resume success rate (0.0-1.0)."""
        if self.resume_count == 0:
            return 0.0
        return self.resume_success_count / self.resume_count

    @property
    def resume_avg_ms(self) -> float:
        """Calculate average resume time in milliseconds."""
        if self.resume_count == 0:
            return 0.0
        return self.resume_total_ms / self.resume_count

    @property
    def total_size_mb(self) -> float:
        """Total checkpoint size in megabytes."""
        return self.total_size_bytes / (1024 * 1024)

    @property
    def messages_extraction_success_rate(self) -> float:
        """Calculate message extraction success rate (0.0-1.0)."""
        total = self.messages_extracted_count + self.messages_extraction_failures
        if total == 0:
            return 0.0
        return self.messages_extracted_count / total
