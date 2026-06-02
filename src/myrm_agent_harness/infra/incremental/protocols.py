"""Protocol for incremental monitoring.

Defines the contract that all monitor implementations must satisfy.

[INPUT]
- (none)

[OUTPUT]
- IncrementalMonitor: Abstract interface for incremental change detection.

[POS]
Protocol for incremental monitoring.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IncrementalMonitor(Protocol):
    """Abstract interface for incremental change detection.

    Implementations compute the delta between current output and historical
    baseline, enabling "only report new content" semantics for monitoring tasks.

    Design:
    - All I/O is string-based (Unix text stream philosophy)
    - Stateless methods — state is managed externally by ``IncrementalMonitorManager``
    - Baseline is updated incrementally, not replaced wholesale
    """

    def is_baseline(self) -> bool:
        """Check if this is the first run (no historical baseline exists).

        Returns:
            True if no baseline data exists yet (first run).
        """
        ...

    def compute_delta(self, current_output: str) -> str:
        """Compute the delta between current output and historical baseline.

        Args:
            current_output: Raw output from the monitoring task (e.g. shell command).

        Returns:
            Delta string containing only new/changed content.
            Empty string if no changes detected.

        Note:
            This method does NOT update the baseline — call ``update_baseline``
            separately after successful delivery.
        """
        ...

    def update_baseline(self, delta: str) -> None:
        """Update the baseline with the given delta.

        Args:
            delta: The delta that was successfully processed/delivered.

        Note:
            Only call this after successful delivery to ensure consistency.
            If delivery fails, the baseline should NOT be updated.
        """
        ...
