"""Browser action capture — record user interactions as structured ActionSteps.

Generic, agent-agnostic capability for capturing browser DOM events (click, type,
select, navigate, etc.) into structured ActionStep sequences. Used by the server
layer to power the Browser Skill Recording Wizard.


[INPUT]
- patchright.async_api::Page (POS: Playwright page for event attachment)

[OUTPUT]
- ActionCaptureEngine: start/stop/pause/resume capture on a Playwright Page
- CaptureCallback: Protocol for real-time step notification
- ActionStep: Immutable captured browser action
- ActionType: Enum of capturable action types
- CaptureSession: Recording session state container
- serialize_step: Single step serialization for SSE
- serialize_session: Full session serialization
- steps_to_natural_language: Human-readable step descriptions

[POS]
Browser action capture submodule. Provides the engine + types + serializers for
recording user browser interactions. Fully self-contained under toolkits/browser/
with zero imports from agent/, runtime/, or backends/.
"""

from .capture_engine import ActionCaptureEngine, CaptureCallback
from .serializer import serialize_session, serialize_step, steps_to_natural_language
from .types import ActionStep, ActionType, CaptureSession

__all__ = [
    "ActionCaptureEngine",
    "ActionStep",
    "ActionType",
    "CaptureCallback",
    "CaptureSession",
    "serialize_session",
    "serialize_step",
    "steps_to_natural_language",
]
