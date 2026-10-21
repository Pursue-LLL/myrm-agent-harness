"""[INPUT] models, context, and tracker components.
[OUTPUT] Public API exports for ambient auxiliary usage accounting and task-dimension attribution.
[POS] myrm_agent_harness.observability.ambient_auxiliary_accounting.__init__
"""

from .context import (
    ambient_auxiliary_task,
    get_current_ambient_task,
)
from .models import (
    AmbientAccountingReport,
    AuxiliaryTaskType,
    AuxiliaryUsageSnapshot,
    TaskCostSummary,
)
from .tracker import (
    AmbientAuxiliaryAccountingTracker,
    get_default_auxiliary_tracker,
)

__all__ = [
    "AmbientAccountingReport",
    "AuxiliaryTaskType",
    "AuxiliaryUsageSnapshot",
    "TaskCostSummary",
    "ambient_auxiliary_task",
    "get_current_ambient_task",
    "AmbientAuxiliaryAccountingTracker",
    "get_default_auxiliary_tracker",
]
