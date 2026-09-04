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
        from myrm_agent_harness.agent.meta_tools.bash._executor.command_classifier import (
            CommandClassifier,
        )
        from myrm_agent_harness.agent.meta_tools.bash._executor.sensitive_parameter_redactor import (
            SensitiveParameterRedactor,
        )
        from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
            get_current_message_id,
        )
        from myrm_agent_harness.agent.middlewares._session_context import (
            get_event_logger,
        )

        event_logger = get_event_logger()
        if not event_logger:
            return

        from myrm_agent_harness.agent.security.redact import redact_sensitive_text

        redactor = SensitiveParameterRedactor()
        redacted_command = redact_sensitive_text(redactor.redact(command))
        command_type, risk_level = CommandClassifier.classify(command)

        event_data: dict[str, object] = {
            "command": redacted_command,
            "exit_code": exit_code,
            "stdout": redact_sensitive_text(stdout),
            "stderr": redact_sensitive_text(stderr),
            "duration_ms": duration_ms,
            "success": success,
            "command_type": command_type.value,
            "risk_level": risk_level.value,
        }

        # Link the side effect to the active assistant turn so lineage views can
        # attribute this command to its originating instruction.
        message_id = get_current_message_id()
        if message_id:
            event_data["message_id"] = message_id

        if error_message:
            event_data["error_message"] = redact_sensitive_text(error_message)

        await event_logger.log("bash_command_executed", event_data)
    except Exception:
        logger.debug("Failed to log bash command execution event", exc_info=True)
