"""Agent health score computation.

Calculates a composite score (0-100) representing the urgency of
background maintenance for a given agent session. Lower score = more urgent.

Components:
- evolution_backlog: pending skills needing attention
- storage_usage_pct: how full the session's storage quota is
- context_fragmentation_pct: ratio of fragmented/compacted context files

[INPUT]
- (none)

[OUTPUT]
- compute_health_score: Compute an agent's maintenance health score.

[POS]
Agent health score computation.
"""

from __future__ import annotations

from .protocols import AgentHealthScore


def compute_health_score(
    *,
    evolution_backlog: int = 0,
    storage_usage_pct: float = 0.0,
    context_fragmentation_pct: float = 0.0,
) -> AgentHealthScore:
    """Compute an agent's maintenance health score.

    Weights (empirically tuned):
    - storage_usage_pct:       40% (most impactful on user experience)
    - evolution_backlog:       35% (affects skill quality)
    - context_fragmentation:   25% (affects response latency)

    Score 100 = perfectly healthy, 0 = critical.
    """
    storage_penalty = min(storage_usage_pct, 100.0) * 0.40
    backlog_penalty = min(evolution_backlog * 5.0, 100.0) * 0.35
    frag_penalty = min(context_fragmentation_pct, 100.0) * 0.25

    raw = 100.0 - storage_penalty - backlog_penalty - frag_penalty
    score = max(0, min(100, int(raw)))

    return AgentHealthScore(
        score=score,
        evolution_backlog=evolution_backlog,
        context_fragmentation_pct=context_fragmentation_pct,
        storage_usage_pct=storage_usage_pct,
    )
