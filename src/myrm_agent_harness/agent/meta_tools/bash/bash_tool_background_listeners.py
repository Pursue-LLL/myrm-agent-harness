"""Background job event listeners for bash_code_execute_tool spawn path.

[INPUT]
- ._background_registry::BackgroundProcessInfo (POS: Background job snapshot type)
- utils.event_utils::dispatch_custom_event (POS: LangGraph custom event dispatch)

[OUTPUT]
- build_background_listeners, classify_background_exit

[POS]
Bridges background process registry events to ptc_notify for frontend ActivityCard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
        BackgroundProcessInfo,
        FinishListener,
        ProgressListener,
    )


def build_background_listeners(
    *, session_id: str, config: RunnableConfig
) -> tuple[FinishListener, ProgressListener]:
    """Return ``(finish_listener, progress_listener)`` bound to this session/config."""
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    async def _on_progress(info: BackgroundProcessInfo, payload: dict[str, object]) -> None:
        message = str(payload.get("message", "")) or info.command
        envelope: dict[str, object] = {
            "event": "ptc_notify",
            "level": "info",
            "message": message,
            "category": f"background:{info.pid}",
            "session_id": session_id,
        }
        for key in ("progress", "step_index", "total_steps"):
            if key in payload:
                envelope[key] = payload[key]
        await dispatch_custom_event("ptc_notify", envelope, config=config)

    async def _on_finish(info: BackgroundProcessInfo) -> None:
        error_category = classify_background_exit(info)
        if info.status == "killed" or (info.status == "exited" and (info.exit_code or 0) == 0):
            level = "info"
        elif error_category in ("oom_killed", "segfault"):
            level = "alert"
        else:
            level = "warn"
        message = f"Background job pid={info.pid} {info.status}" + (
            f" (exit_code={info.exit_code})" if info.exit_code is not None else ""
        )
        envelope: dict[str, object] = {
            "event": "ptc_notify",
            "level": level,
            "message": message,
            "category": f"background:{info.pid}",
            "progress": 100,
            "session_id": session_id,
        }
        if error_category is not None:
            envelope["error_category"] = error_category
        await dispatch_custom_event("ptc_notify", envelope, config=config)

    return _on_finish, _on_progress


def classify_background_exit(info: BackgroundProcessInfo) -> str | None:
    """Map ``BackgroundProcessInfo.exit_code`` to a UI-friendly error category."""
    if info.status == "exited" and (info.exit_code or 0) == 0:
        return None
    code = info.exit_code
    if code is None:
        return None
    if code == 137:
        return "oom_killed"
    if code == 139:
        return "segfault"
    if code == 143 or code < 0:
        return "signal_terminated"
    if info.status == "killed":
        return None
    return "nonzero_exit"
