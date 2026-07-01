"""Record skill selection usage for the Curator stats pipeline.

[INPUT]
- backends.skills.stats_collector::SkillStatsCollector (POS: Usage stats persistence)
- backends.skills.types::SkillMetadata (POS: Skill runtime metadata)

[OUTPUT]
- record_skill_selection: Write .stats.json on skill select / [use skill]
- reset_turn_usage_dedupe: Per-turn dedupe reset (SkillAgent.run)
- flush_skill_usage_stats: Session-end flush (_cleanup_session)

[POS]
Agent-runtime bridge from skill_select_tool and explicit [use skill] to Curator usage stats.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pathlib import Path

from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

_collector: SkillStatsCollector | None = None
_turn_recorded: ContextVar[set[str] | None] = ContextVar("skill_usage_turn_recorded", default=None)


def _get_collector() -> SkillStatsCollector:
    global _collector
    if _collector is None:
        _collector = SkillStatsCollector(Path.home() / ".myrm")
    return _collector


def reset_turn_usage_dedupe() -> None:
    """Clear per-turn dedupe set. Call at the start of each agent run."""
    _turn_recorded.set(set())


def record_skill_selection(
    skill_meta: SkillMetadata,
    *,
    success: bool = True,
    duration_ms: float = 0.0,
) -> None:
    """Record a skill selection event (at most once per skill per agent turn)."""
    if not skill_meta.storage_path:
        return

    skill_path = Path(skill_meta.storage_path)
    if not skill_path.is_dir():
        return

    recorded = _turn_recorded.get()
    if recorded is None:
        recorded = set()
        _turn_recorded.set(recorded)
    if skill_meta.name in recorded:
        return
    recorded.add(skill_meta.name)

    try:
        _get_collector().record_usage(skill_path, success=success, duration_ms=duration_ms)
    except Exception:
        logger.warning("Failed to record skill usage for %s", skill_meta.name, exc_info=True)


def flush_skill_usage_stats() -> None:
    """Flush pending usage stats to disk (session end / shutdown)."""
    if _collector is not None:
        _collector.flush()
