"""Progress reporting for the LLM phases of a wiki maintenance run.

[INPUT]
- utils.logger_utils::get_agent_logger (POS: agent logger)

[OUTPUT]
- MaintainPhase: the LLM phases of a full maintenance run
- MaintainProgress: how many pages of a phase are done
- MaintainProgressCallback: observer signature
- report_progress: notify an observer without ever letting it break the run

[POS]
A full maintenance run asks the model about up to 5 sampled pages (drift review) and then up to 20 pages
(link discovery), one call after the other, so a run takes minutes. The host passes a callback to see where
the run is; the engine itself keeps no state and a missing or failing observer changes nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class MaintainPhase(StrEnum):
    """LLM phase of a full maintenance run, in execution order."""

    DRIFT_REVIEW = "drift_review"
    LINK_DISCOVERY = "link_discovery"


@dataclass(frozen=True, slots=True)
class MaintainProgress:
    """``done`` of ``total`` pages of ``phase`` have been handled."""

    phase: MaintainPhase
    done: int
    total: int


type MaintainProgressCallback = Callable[[MaintainProgress], None]


def report_progress(callback: MaintainProgressCallback | None, phase: MaintainPhase, done: int, total: int) -> None:
    """Tell the observer how far ``phase`` is; an observer error is logged, never raised."""
    if callback is None:
        return
    try:
        callback(MaintainProgress(phase, done, total))
    except Exception as e:
        logger.warning(f"Maintain progress observer failed: {e}")
