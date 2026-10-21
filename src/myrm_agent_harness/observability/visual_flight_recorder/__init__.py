"""
[INPUT]: Submodules models and recorder.
[OUTPUT]: Public facade exports for visual_flight_recorder.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/visual_flight_recorder/__init__.py
"""

from .models import (
    FlightRecorderConfig,
    VisualFailureSlice,
    VisualFrame,
)
from .recorder import (
    VisualFlightRecorder,
    get_default_visual_flight_recorder,
)

__all__ = [
    "FlightRecorderConfig",
    "VisualFailureSlice",
    "VisualFrame",
    "VisualFlightRecorder",
    "get_default_visual_flight_recorder",
]
