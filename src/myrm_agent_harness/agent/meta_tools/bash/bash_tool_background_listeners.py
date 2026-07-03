"""Background job event listeners for bash_code_execute_tool spawn path.

[INPUT]
- ._background_registry::BackgroundProcessInfo (POS: Background job snapshot type)
- utils.event_utils::dispatch_custom_event (POS: LangGraph custom event dispatch)

[OUTPUT]
- build_background_listeners, classify_background_exit

[POS]
Bridges background process registry events to ptc_notify for frontend ActivityCard.
Natural ``exited`` jobs emit finish ptc_notify and invoke the optional server finish handler.
``killed`` jobs (session cancel via ``kill_session_jobs``) emit nothing on finish.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
        BackgroundProcessInfo,
        FinishListener,
        ProgressListener,
    )


logger = logging.getLogger(__name__)


def build_background_listeners(
    *, session_id: str, config: RunnableConfig
) -> tuple[FinishListener, ProgressListener]:
    """Return ``(finish_listener, progress_listener)`` bound to this session/config."""
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event
    from myrm_agent_harness.utils.runtime.background_job_finish_registry import (
        get_global_background_job_finish_handler,
    )

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
        # Session cancel kills jobs with status=killed — skip finish UI noise
        # (no success toast, no chat persistence; see server finish handler guard).
        if info.status == "killed":
            return

        error_category = classify_background_exit(info)
        if info.status == "exited" and (info.exit_code or 0) == 0:
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

        finish_handler = get_global_background_job_finish_handler()
        if finish_handler is not None and session_id and info.status == "exited":
            from myrm_agent_harness.utils.runtime.background_job_finish_registry import (
                BackgroundJobFinishResult,
            )

            try:
                await finish_handler.on_background_job_finish(
                    BackgroundJobFinishResult(
                        session_id=session_id,
                        pid=info.pid,
                        command=info.command,
                        status=info.status,
                        exit_code=info.exit_code,
                        error_category=error_category,
                    )
                )
            except Exception:
                logger.exception(
                    "Background job finish handler failed for pid=%s session=%s",
                    info.pid,
                    session_id,
                )

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
