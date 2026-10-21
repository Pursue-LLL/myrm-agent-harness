"""[INPUT] ContextVar primitives and task taxonomy definitions.
[OUTPUT] Ambient context manager automatically binding auxiliary task dimensions without intrusive signature changes.
[POS] myrm_agent_harness.observability.ambient_auxiliary_accounting.context

Context manager for ambient auxiliary accounting:
Allows code scopes like `with ambient_auxiliary_task(AuxiliaryTaskType.VISION_PREP):`
to tag downstream LLM and tool calls with the active task dimension.
"""

from collections.abc import Generator
from contextlib import contextmanager
import contextvars

from .models import AuxiliaryTaskType

# ContextVar storing active (task_type, custom_task_name, model_override)
_active_auxiliary_context: contextvars.ContextVar[tuple[AuxiliaryTaskType, str, str]] = contextvars.ContextVar(
    "active_auxiliary_context",
    default=(AuxiliaryTaskType.MAIN_DIALOGUE, "", ""),
)


def get_current_ambient_task() -> tuple[AuxiliaryTaskType, str, str]:
    """Retrieve the current ambient auxiliary task dimension, custom name, and model override."""
    return _active_auxiliary_context.get()


@contextmanager
def ambient_auxiliary_task(
    task_type: AuxiliaryTaskType | str,
    custom_task_name: str = "",
    model: str = "",
) -> Generator[tuple[AuxiliaryTaskType, str, str], None, None]:
    """Scoped context manager setting the active auxiliary task dimension.

    Supports nesting; resets to the outer or default task dimension upon scope exit.
    """
    resolved_type: AuxiliaryTaskType
    if isinstance(task_type, AuxiliaryTaskType):
        resolved_type = task_type
    else:
        try:
            resolved_type = AuxiliaryTaskType(task_type.strip().lower())
        except ValueError:
            resolved_type = AuxiliaryTaskType.CUSTOM

    new_val = (resolved_type, custom_task_name.strip(), model.strip())
    token = _active_auxiliary_context.set(new_val)
    try:
        yield new_val
    finally:
        _active_auxiliary_context.reset(token)
