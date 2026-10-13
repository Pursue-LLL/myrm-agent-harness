"""Run-scoped bridge from skill activity to the Curator stats pipeline.

A run collects which skills it used (selected, or executed tools under) and
how many tool calls attributed to them failed. The run's end turns that into
exactly one ``.stats.json`` use per skill, so the success rate counts runs with
an observed outcome instead of tool calls or skill loads.

[INPUT]
- backends.skills.stats_collector::SkillStatsCollector (POS: Usage stats persistence)
- backends.skills.types::SkillMetadata (POS: Skill runtime metadata)

[OUTPUT]
- set_stats_collector / get_injected_stats_collector: Shared collector injection (server wiring)
- begin_skill_run_usage: Open the run scope (SkillAgent.run start)
- record_skill_selection: Note that a skill was selected / [use skill]
- record_skill_execution: Note one tool-call outcome attributed to a skill
- commit_skill_run_usage: Write one use per skill and close the scope (SkillAgent.run end)
- flush_skill_usage_stats: Session-end flush (_cleanup_session)

[POS]
Agent-runtime bridge from skill_select_tool, explicit [use skill] and tool outcomes to Curator usage stats.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SkillRunUse:
    """What one run did with one skill."""

    path: Path
    tool_calls: int = 0
    failed_calls: int = 0

    @property
    def outcome(self) -> bool | None:
        """None while no tool call is attributed to the skill; otherwise False once most of them failed.

        Majority, not "any": long runs hit incidental, recovered errors, which must not read as a failed skill.
        """
        if self.tool_calls == 0:
            return None
        return self.failed_calls * 2 <= self.tool_calls


_collector: SkillStatsCollector | None = None
_injected_collector: SkillStatsCollector | None = None
# One mutable dict per run: tools run in copied contexts, so records must mutate the run's dict instead of rebinding.
_run_usage: ContextVar[dict[str, _SkillRunUse] | None] = ContextVar("skill_run_usage", default=None)


def set_stats_collector(collector: SkillStatsCollector | None) -> None:
    """Inject the process-wide SkillStatsCollector (called from server on startup)."""
    global _injected_collector, _collector
    _injected_collector = collector
    _collector = collector


def get_injected_stats_collector() -> SkillStatsCollector | None:
    """Return the injected collector, if any."""
    return _injected_collector


def _get_collector() -> SkillStatsCollector:
    global _collector
    if _injected_collector is not None:
        return _injected_collector
    if _collector is None:
        _collector = SkillStatsCollector(Path.home() / ".myrm")
    return _collector


def _skill_dir(storage_path: str | None) -> Path | None:
    if not storage_path:
        return None
    path = Path(storage_path)
    return path if path.is_dir() else None


def _write_use(skill_name: str, skill_path: Path, *, success: bool | None) -> None:
    try:
        _get_collector().record_use(skill_path, success=success)
    except Exception:
        logger.warning("Failed to record skill usage for %s", skill_name, exc_info=True)


def begin_skill_run_usage() -> None:
    """Open a fresh run scope. A nested run opens its own and leaves the outer one untouched."""
    _run_usage.set({})


def record_skill_selection(skill_meta: SkillMetadata) -> None:
    """Note that the run selected a skill. Without an open run scope the use is written immediately."""
    skill_path = _skill_dir(skill_meta.storage_path)
    if skill_path is None:
        return

    run = _run_usage.get()
    if run is None:
        _write_use(skill_meta.name, skill_path, success=None)
        return
    run.setdefault(skill_meta.name, _SkillRunUse(skill_path))


def record_skill_execution(skill_name: str, storage_path: str | None, *, success: bool) -> None:
    """Note the outcome of one tool call that is attributed to the skill (ignored without an open run scope)."""
    skill_path = _skill_dir(storage_path)
    run = _run_usage.get()
    if skill_path is None or run is None:
        return

    use = run.setdefault(skill_name, _SkillRunUse(skill_path))
    use.tool_calls += 1
    use.failed_calls += not success


def commit_skill_run_usage() -> None:
    """Write one use per skill the run touched and close the scope."""
    run = _run_usage.get()
    if run is None:
        return
    _run_usage.set(None)

    for skill_name, use in run.items():
        _write_use(skill_name, use.path, success=use.outcome)


def flush_skill_usage_stats() -> None:
    """Flush pending usage stats to disk (session end / shutdown)."""
    collector = _injected_collector or _collector
    if collector is not None:
        collector.flush()
