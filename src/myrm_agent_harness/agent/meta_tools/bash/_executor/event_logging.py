"""Event logging for bash command execution.

[INPUT]
command_classifier::CommandClassifier (POS: Command type and risk classification)
sensitive_parameter_redactor::SensitiveParameterRedactor (POS: Sensitive parameter redaction)
middlewares._session_context::get_event_logger (POS: Session-scoped event logger accessor)

[OUTPUT]
log_bash_command_execution: Log a bash command execution event to EventLog.

[POS]
Event logging for bash command execution. Handles command redaction, classification,
and structured event emission to EventLog. Failure-safe (never affects main flow).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def log_bash_command_execution(
    command: str,
    session_id: str,
    exit_code: int,
    stdout: str,
    stderr: str,
    duration_ms: int,
    success: bool,
    error_message: str = "",
) -> None:
    """Log a bash command execution event to EventLog.

    Failure-safe: exceptions are caught and logged at DEBUG level.
    """
    try:
        from myrm_agent_harness.agent.meta_tools.bash.command_classifier import (
            CommandClassifier,
        )
        from myrm_agent_harness.agent.meta_tools.bash.sensitive_parameter_redactor import (
            SensitiveParameterRedactor,
        )
        from myrm_agent_harness.agent.middlewares._session_context import (
            get_event_logger,
        )

        event_logger = get_event_logger()
        if not event_logger:
            return

        redactor = SensitiveParameterRedactor()
        redacted_command = redactor.redact(command)
        command_type, risk_level = CommandClassifier.classify(command)

        event_data: dict[str, object] = {
            "command": redacted_command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
            "success": success,
            "command_type": command_type.value,
            "risk_level": risk_level.value,
        }

        if error_message:
            event_data["error_message"] = error_message

        await event_logger.log("bash_command_executed", event_data)
    except Exception:
        logger.debug("Failed to log bash command execution event", exc_info=True)
