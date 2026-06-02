"""Message filter pipeline for composing multiple filters.

[INPUT]
- (none)

[OUTPUT]
- MessageFilterPipeline: Pipeline that applies multiple filters in sequence.

[POS]
Message filter pipeline for composing multiple filters.
"""

import logging
import time
from typing import Any

from ..engine import check_capability
from ..types import Capability
from .base import FilterContext, MessageFilter
from .filter_stats import FilterStats

logger = logging.getLogger(__name__)


class MessageFilterPipeline:
    """Pipeline that applies multiple filters in sequence.

    The pipeline evaluates each message against all filters. If any filter
    returns True (should_filter), the message is excluded from the output.

    This design enables:
    - Composing multiple filters (SystemRole + PII + Custom)
    - Short-circuit evaluation (first match filters out)
    - Extensibility (add new filters without changing core logic)

    Example:
        >>> pipeline = MessageFilterPipeline([
        ...     SystemRoleFilter(config),
        ...     PIIRedactionFilter(config),
        ... ])
        >>> filtered = pipeline.filter_messages(messages, context)
    """

    def __init__(self, filters: list[MessageFilter], enable_stats: bool = True):
        """Initialize pipeline with a list of filters.

        Args:
            filters: List of filters to apply in order
            enable_stats: Enable performance statistics tracking
        """
        self.filters = filters
        self.stats = FilterStats() if enable_stats else None

    def filter_messages(
        self,
        messages: list[dict[str, Any]],
        context: FilterContext,
        bypass_with_capability: Capability | None = None,
    ) -> list[dict[str, Any]]:
        """Filter a list of messages through all filters with fail-safe error handling.

        If a filter raises an exception, the error is logged and the filter is skipped.
        This ensures that a buggy filter doesn't break the entire system.

        Supports permission-based bypass: if user has the specified capability,
        all filters are bypassed and original messages are returned.

        Args:
            messages: List of messages to filter
            context: Runtime context for filtering decisions
            bypass_with_capability: Optional capability that allows bypassing all filters

        Returns:
            Filtered list of messages (messages where all filters returned False)
        """
        # Check permission bypass
        if bypass_with_capability is not None:
            try:
                has_permission = check_capability(bypass_with_capability)
                if has_permission:
                    logger.info(
                        "Message filtering bypassed for user with capability: %s",
                        bypass_with_capability.permission,
                        extra={
                            "user_id": context.user_id,
                            "capability": bypass_with_capability.permission,
                        },
                    )
                    return messages
            except Exception as e:
                logger.warning(
                    "Failed to check capability for filter bypass: %s",
                    str(e),
                    extra={"user_id": context.user_id, "error": str(e)},
                )

        result = []
        for message in messages:
            # Check if any filter wants to filter this message
            should_remove = False
            for filter in self.filters:
                filter_name = filter.__class__.__name__

                # Measure filter execution time
                start_time = time.perf_counter()
                try:
                    if filter.should_filter(message, context):
                        should_remove = True
                        # Track performance
                        if self.stats:
                            elapsed_ms = (time.perf_counter() - start_time) * 1000
                            self.stats.track(filter_name, elapsed_ms)
                        break  # Short-circuit: first match filters out
                except Exception as e:
                    # Log error but don't break the pipeline
                    logger.error(
                        "Filter %s failed: %s",
                        filter_name,
                        str(e),
                        exc_info=True,
                        extra={
                            "filter": filter_name,
                            "user_id": context.user_id,
                            "error": str(e),
                        },
                    )
                    # Continue to next filter instead of crashing
                    continue
                finally:
                    # Always track timing, even if filter failed
                    if self.stats and filter_name:
                        elapsed_ms = (time.perf_counter() - start_time) * 1000
                        if elapsed_ms > 0:  # Only track if measurable
                            self.stats.track(filter_name, elapsed_ms)

            if not should_remove:
                result.append(message)

        return result

    def add_filter(self, filter: MessageFilter) -> None:
        """Add a filter to the pipeline.

        Args:
            filter: Filter to add
        """
        self.filters.append(filter)

    def remove_filter(self, filter_name: str) -> bool:
        """Remove a filter from the pipeline by name.

        Args:
            filter_name: Name of the filter to remove

        Returns:
            True if filter was found and removed, False otherwise
        """
        for i, f in enumerate(self.filters):
            if f.get_name() == filter_name:
                self.filters.pop(i)
                return True
        return False

    def get_filter_names(self) -> list[str]:
        """Get names of all filters in the pipeline.

        Returns:
            List of filter names
        """
        return [f.get_name() for f in self.filters]

    def dry_run(
        self,
        messages: list[dict[str, Any]],
        context: FilterContext,
        test_filters: list[MessageFilter] | None = None,
    ) -> dict[str, Any]:
        """Simulate filtering with test configuration without applying changes.

        Useful for testing new filter rules before deploying to production.

        Args:
            messages: Messages to test
            context: Runtime context
            test_filters: Optional list of test filters (if None, uses current filters)

        Returns:
            Dictionary containing:
            - original: Original messages
            - filtered: Filtered messages
            - stats: Filtering statistics
        """
        # Save current filters
        original_filters = self.filters
        original_stats = self.stats

        try:
            # Temporarily use test filters if provided
            if test_filters is not None:
                self.filters = test_filters

            # Reset stats for this dry run
            self.stats = FilterStats()

            # Run filtering
            filtered = self.filter_messages(messages, context)

            # Collect stats
            stats_summary = self.stats.get_summary() if self.stats else {}

            return {
                "original": messages,
                "filtered": filtered,
                "stats": {
                    "total_messages": len(messages),
                    "filtered_count": len(messages) - len(filtered),
                    "remaining_count": len(filtered),
                    "filter_ratio": (
                        (len(messages) - len(filtered)) / len(messages)
                        if messages
                        else 0.0
                    ),
                    "performance": stats_summary,
                },
            }
        finally:
            # Restore original state
            self.filters = original_filters
            self.stats = original_stats
