"""Approval Interception Middleware.

Intercepts user text input when the agent is in a pending_approval state
and converts it into a Command(resume=...) to resume execution,
preventing the text from polluting the LLM context.

[INPUT]
- agent.streaming.types::AgentEventType, (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- check_pending_approval: Check if the agent is currently interrupted (awaiting app...
- intercept_approval_text: Intercept text input if agent is awaiting approval.

[POS]
Approval Interception Middleware.
"""

from __future__ import annotations

import asyncio

from langgraph.types import Command

from myrm_agent_harness.agent.middlewares.approval_interception.recognizer import (
    ApprovalIntent,
    ApprovalIntentRecognizer,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType, ApprovalInterceptedEventData
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


async def check_pending_approval(checkpointer: object, thread_id: str) -> bool:
    """Check if the agent is currently interrupted (awaiting approval)."""
    if not checkpointer:
        return False

    try:
        checkpoint_config = {"configurable": {"thread_id": thread_id}}
        # We only need to check if there are tasks with interrupts in the current state
        state = await checkpointer.aget_tuple(checkpoint_config)
        if not state or not state.tasks:
            return False

        # Check if any task has interrupts
        return any(hasattr(task, "interrupts") and task.interrupts for task in state.tasks)
    except Exception as e:
        logger.warning("Failed to check pending approval state: %s", e)
        return False


async def intercept_approval_text(
    query: str | list[dict[str, object]],
    checkpointer: object,
    thread_id: str,
    message_id: str,
    output_queue: asyncio.Queue[dict[str, object]] | None,
) -> Command | str | list[dict[str, object]]:
    """Intercept text input if agent is awaiting approval.

    If intercepted, returns a Command object to resume execution.
    If not intercepted, returns the original query.
    Emits an APPROVAL_INTERCEPTED event if intercepted.
    """
    # Only intercept text queries
    if isinstance(query, Command):
        return query

    text_content = ""
    if isinstance(query, str):
        text_content = query
    elif isinstance(query, list):
        text_content = next((p.get("text", "") for p in query if isinstance(p, dict) and p.get("type") == "text"), "")

    # Check if we are in a pending approval state
    is_pending = await check_pending_approval(checkpointer, thread_id)
    if not is_pending:
        return query

    # If pending approval but no text content (e.g., user sent an image only),
    # we still want to intercept it as a rejection with feedback to unpause the graph.
    if not text_content:
        text_content = "[Non-text input received]"

    # We are pending approval, recognize intent
    intent, feedback = ApprovalIntentRecognizer.recognize(text_content)

    # Construct resume payload
    resume_payload: dict[str, object] = {}

    if intent == ApprovalIntent.FEEDBACK:
        resume_payload = {"decision": "feedback", "feedback": feedback}
        logger.info("Intercepted approval text as FEEDBACK: %s", text_content[:50])
    else:
        resume_payload = {"decision": intent.value}
        logger.info("Intercepted approval text as %s: %s", intent.name, text_content[:50])

    event_data = ApprovalInterceptedEventData(decision=resume_payload["decision"], original_text=text_content)

    # Emit event
    event = {
        "type": AgentEventType.APPROVAL_INTERCEPTED.value,
        "data": {
            "decision": event_data.decision,
            "original_text": event_data.original_text,
        },
        "messageId": message_id,
    }

    # Put event in queue if available
    if output_queue:
        await output_queue.put(event)

    # Return Command to replace the original query
    return Command(resume=resume_payload)
