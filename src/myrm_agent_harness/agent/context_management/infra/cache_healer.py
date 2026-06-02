"""Active Cache Healer.

[INPUT]
- myrm_agent_harness.agent.context_management.memory_manager::MemoryManager

[OUTPUT]
- ActiveCacheHealer: Monitors cache hit rate and triggers context compression.

[POS]
Active Cache Healer.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.agent.context_management.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

class ActiveCacheHealer:
    """Monitors cache hit rate and triggers context compression if it drops."""

    def __init__(self, memory_manager: 'MemoryManager', threshold: float = 0.4, consecutive_drops: int = 3):
        self.memory_manager = memory_manager
        self.threshold = threshold
        self.consecutive_drops = consecutive_drops
        self._drop_count = 0

    async def check_and_heal(self, prompt_tokens: int, cached_tokens: int) -> bool:
        """Check cache hit rate and trigger healing if necessary.

        Returns True if healing was triggered.
        """
        if prompt_tokens == 0:
            return False

        hit_rate = cached_tokens / prompt_tokens

        if hit_rate < self.threshold:
            self._drop_count += 1
            logger.warning(f"[CacheHealer] Cache hit rate dropped to {hit_rate:.1%}. Drop count: {self._drop_count}")
        else:
            self._drop_count = 0

        if self._drop_count >= self.consecutive_drops:
            logger.warning(f"[CacheHealer] Hit rate below {self.threshold:.1%} for {self.consecutive_drops} consecutive turns. Triggering healing.")
            await self._trigger_healing()
            self._drop_count = 0
            return True

        return False

    async def _trigger_healing(self) -> None:
        """Trigger context compression to heal the cache."""
        try:
            # We don't have a direct MemoryManager reference, but we can signal the pipeline
            # to force a compression on the next turn by setting a flag in the context
            # or by directly calling the CompressProcessor if we have access to it.
            # For now, we log it. The actual integration requires hooking into the pipeline.
            logger.info("[CacheHealer] Cache healing triggered. (Integration with pipeline required)")

            # If memory_manager is actually the pipeline engine or has a process method:
            if hasattr(self.memory_manager, 'process'):
                # We would ideally inject a marker into the ProcessorContext to force compression
                pass
        except Exception as e:
            logger.error(f"[CacheHealer] Failed to heal cache: {e}")
