"""Checkpoint metrics for monitoring and observability.

Tracks performance and behavior of checkpoint operations.


[INPUT]
- dataclasses::dataclass (POS: Python dataclass decorator)

[OUTPUT]
- CheckpointMetrics: Checkpoint performance and behavior metrics

[POS]
Checkpoint monitoring metrics. Provides observability for checkpoint operations, supporting performance analysis and anomaly detection.
Integrated into BrowserObservability, unified with recording and progress notification features.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckpointMetrics:
    """Checkpoint operation metrics for monitoring and tuning.

    Tracks performance and behavior of checkpoint/recovery operations:
    - Save performance: frequency, duration, incremental ratio
    - Recovery performance: duration, success rate
    - Session Vault integration: save frequency, cache effectiveness

    All durations are in milliseconds for precision.
    """

    # Save metrics
    save_count: int = 0
    save_total_ms: float = 0.0
    save_skipped_count: int = 0  # Skipped due to no state change

    # Recovery metrics
    recovery_count: int = 0
    recovery_total_ms: float = 0.0
    recovery_failures: int = 0

    # Session Vault integration
    vault_save_count: int = 0
    vault_save_total_ms: float = 0.0
    vault_cache_hits: int = 0

    # Metadata access
    metadata_extractions: int = 0
    metadata_extraction_total_ms: float = 0.0

    # Hash computation (for incremental saving)
    hash_computations: int = 0
    hash_total_ms: float = 0.0

    # Warnings and errors
    hash_collision_count: int = 0
    metadata_missing_count: int = 0

    @property
    def save_avg_ms(self) -> float:
        """Average checkpoint save duration in milliseconds."""
        return self.save_total_ms / self.save_count if self.save_count > 0 else 0.0

    @property
    def recovery_avg_ms(self) -> float:
        """Average recovery duration in milliseconds."""
        return self.recovery_total_ms / self.recovery_count if self.recovery_count > 0 else 0.0

    @property
    def incremental_ratio(self) -> float:
        """Ratio of skipped saves (0.0 = never skip, 1.0 = always skip).

        Note: save_skipped_count is counted during metadata tracking,
        while save_count tracks all aput() calls.
        The ratio indicates how often SessionVault save is skipped.
        """
        total_vault_attempts = self.vault_save_count + self.save_skipped_count
        return self.save_skipped_count / total_vault_attempts if total_vault_attempts > 0 else 0.0

    @property
    def recovery_success_rate(self) -> float:
        """Recovery success rate (0.0 to 1.0)."""
        total_recoveries = self.recovery_count + self.recovery_failures
        return self.recovery_count / total_recoveries if total_recoveries > 0 else 1.0

    @property
    def vault_save_avg_ms(self) -> float:
        """Average Session Vault save duration in milliseconds."""
        return self.vault_save_total_ms / self.vault_save_count if self.vault_save_count > 0 else 0.0

    def to_dict(self) -> dict[str, float]:
        """Export metrics as dictionary for logging/monitoring.

        Returns:
            Dictionary with all metrics and computed properties
        """
        return {
            "save_count": self.save_count,
            "save_avg_ms": self.save_avg_ms,
            "save_skipped_count": self.save_skipped_count,
            "incremental_ratio": self.incremental_ratio,
            "recovery_count": self.recovery_count,
            "recovery_avg_ms": self.recovery_avg_ms,
            "recovery_success_rate": self.recovery_success_rate,
            "recovery_failures": self.recovery_failures,
            "vault_save_count": self.vault_save_count,
            "vault_save_avg_ms": self.vault_save_avg_ms,
            "hash_computations": self.hash_computations,
            "hash_avg_ms": self.hash_total_ms / self.hash_computations if self.hash_computations > 0 else 0.0,
            "metadata_extractions": self.metadata_extractions,
            "metadata_extraction_avg_ms": self.metadata_extraction_total_ms / self.metadata_extractions
            if self.metadata_extractions > 0
            else 0.0,
            "warnings": {
                "hash_collisions": self.hash_collision_count,
                "metadata_missing": self.metadata_missing_count,
            },
        }
