"""Lifecycle manager governing tiered storage migration and archival.

[INPUT]
- toolkits.memory.decay.scorer::EbbinghausDecayScorer (POS: Ebbinghaus exponential decay and RFM frequency
  reinforcement scoring function.)
- toolkits.memory.decay.types::DecayScorerConfig, MemoryDecayProfile, StorageTier, TierMigrationReport (POS:
  Domain models and type definitions for Ebbinghaus decay and tiered storage lifecycle.)

[OUTPUT]
- TieredStorageLifecycleManager: Orchestrates hot/warm/cold tier transitions based on dynamic decay
  evaluations.

[POS]
Lifecycle manager governing tiered storage migration and archival.
"""

import time
from collections import defaultdict

from myrm_agent_harness.toolkits.memory.decay.scorer import (
    EbbinghausDecayScorer,
)
from myrm_agent_harness.toolkits.memory.decay.types import (
    DecayScorerConfig,
    MemoryDecayProfile,
    StorageTier,
    TierMigrationReport,
)


class TieredStorageLifecycleManager:
    """Orchestrates hot/warm/cold tier transitions based on dynamic decay evaluations."""

    def __init__(
        self,
        scorer: EbbinghausDecayScorer | None = None,
        config: DecayScorerConfig | None = None,
    ) -> None:
        self.scorer = scorer or EbbinghausDecayScorer(config=config)
        self._profiles: dict[str, MemoryDecayProfile] = {}
        self._tier_buckets: dict[StorageTier, set[str]] = defaultdict(set)

    def register_memory(
        self,
        memory_id: str,
        content: str,
        importance: float,
        created_at: float | None = None,
        pinned: bool = False,
    ) -> MemoryDecayProfile:
        """Register a new memory entry into the lifecycle manager."""
        now = time.time() if created_at is None else created_at
        profile = MemoryDecayProfile(
            memory_id=memory_id,
            content=content,
            importance=min(1.0, max(0.1, importance)),
            created_at=now,
            last_accessed_at=now,
            access_count=1,
            pinned=pinned,
            current_score=1.0,
            current_tier=StorageTier.HOT,
        )

        # Initial scoring
        score, tier = self.scorer.calculate_score(profile, current_time=now)
        profile.current_score = score
        profile.current_tier = tier

        # Store and bucket
        self._profiles[memory_id] = profile
        self._tier_buckets[tier].add(memory_id)
        return profile

    def touch_memory(
        self, memory_id: str, current_time: float | None = None
    ) -> tuple[float, StorageTier] | None:
        """Record an access/retrieval event on an active memory."""
        profile = self._profiles.get(memory_id)
        if not profile:
            return None

        old_tier = profile.current_tier
        score, new_tier = self.scorer.touch(profile, current_time=current_time)

        if old_tier != new_tier:
            self._tier_buckets[old_tier].discard(memory_id)
            self._tier_buckets[new_tier].add(memory_id)

        return score, new_tier

    def evaluate_and_migrate(
        self, current_time: float | None = None
    ) -> TierMigrationReport:
        """Run periodic decay re-evaluation and execute tier bucket migrations."""
        now = time.time() if current_time is None else current_time
        migrated_ids: list[str] = []

        for mem_id, profile in self._profiles.items():
            old_tier = profile.current_tier
            new_score, new_tier = self.scorer.calculate_score(profile, current_time=now)
            profile.current_score = new_score
            profile.current_tier = new_tier

            if old_tier != new_tier:
                self._tier_buckets[old_tier].discard(mem_id)
                self._tier_buckets[new_tier].add(mem_id)
                migrated_ids.append(mem_id)

        return TierMigrationReport(
            total_evaluated=len(self._profiles),
            hot_count=len(self._tier_buckets[StorageTier.HOT]),
            warm_count=len(self._tier_buckets[StorageTier.WARM]),
            cold_count=len(self._tier_buckets[StorageTier.COLD]),
            migrated_count=len(migrated_ids),
            migrated_memory_ids=migrated_ids,
        )

    def revive_memory(
        self,
        memory_id: str,
        boost_importance: float | None = None,
        current_time: float | None = None,
    ) -> MemoryDecayProfile | None:
        """Reactivate an archived or cold memory, elevating it back to the HOT tier."""
        profile = self._profiles.get(memory_id)
        if not profile:
            return None

        now = time.time() if current_time is None else current_time
        if boost_importance is not None:
            profile.importance = min(1.0, max(profile.importance, boost_importance))

        profile.last_accessed_at = now
        profile.access_count += 2  # Boost frequency on manual revival

        old_tier = profile.current_tier
        score, new_tier = self.scorer.calculate_score(profile, current_time=now)
        profile.current_score = score
        profile.current_tier = new_tier

        if old_tier != new_tier:
            self._tier_buckets[old_tier].discard(memory_id)
            self._tier_buckets[new_tier].add(memory_id)

        return profile

    def get_profile(self, memory_id: str) -> MemoryDecayProfile | None:
        """Fetch profile for a specific memory item."""
        return self._profiles.get(memory_id)

    def get_profiles_by_tier(self, tier: StorageTier) -> list[MemoryDecayProfile]:
        """List all active profiles currently categorized in the specified tier."""
        ids = self._tier_buckets.get(tier, set())
        return [self._profiles[mid] for mid in ids if mid in self._profiles]

    def export_cold_archive(self) -> list[dict[str, str | float | int | bool]]:
        """Export serialized representation of cold memories for lightweight JSONL archival."""
        cold_profiles = self.get_profiles_by_tier(StorageTier.COLD)
        return [
            {
                "memory_id": p.memory_id,
                "content": p.content,
                "importance": p.importance,
                "created_at": p.created_at,
                "last_accessed_at": p.last_accessed_at,
                "access_count": p.access_count,
                "pinned": p.pinned,
                "score": p.current_score,
                "tier": p.current_tier.value,
            }
            for p in cold_profiles
        ]
