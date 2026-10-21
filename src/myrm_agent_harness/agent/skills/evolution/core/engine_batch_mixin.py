"""SkillEvolutionEngine batch evolution mixin.

[POS]
Concurrent evolve_multiple_concurrent entry for SkillEvolutionEngine.
"""

from __future__ import annotations

import asyncio
import logging

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionProposal,
    EvolutionRequest,
    EvolutionType,
)

logger = logging.getLogger(__name__)


class SkillEvolutionEngineBatchMixin:
    async def evolve_multiple_concurrent(self, requests: list[EvolutionRequest]) -> list[EvolutionProposal | None]:
        """Evolve multiple skills concurrently with rate limiting."""
        if not requests:
            return []

        async def _evolve_with_limit(req: EvolutionRequest) -> EvolutionProposal | None:
            async with self._semaphore:
                if req.evolution_type == EvolutionType.FIX:
                    return await self.fix_skill(req.skill_id or "", req.reason)
                elif req.evolution_type == EvolutionType.DERIVED:
                    return await self.derive_skill_simple(req.skill_id or "", req.user_feedback)
                elif req.evolution_type == EvolutionType.OPTIMIZE_DESCRIPTION:
                    return await self.optimize_description(req.skill_id or "")
                elif req.evolution_type == EvolutionType.CAPTURED:
                    return None
                return None

        results = await asyncio.gather(*[_evolve_with_limit(req) for req in requests], return_exceptions=True)

        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Concurrent evolution request {i} failed: {result}")
                final_results.append(None)
            else:
                final_results.append(result)

        return final_results
