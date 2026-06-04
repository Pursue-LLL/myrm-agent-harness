import asyncio
import json
from collections.abc import AsyncIterable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from myrm_agent_harness.agent.streaming.stream_buffer import CancellationToken


async def run_dynamic_workflow_stream(
    llm: BaseChatModel,
    query: str,
    chat_history: list[BaseMessage],
    cancel_token: CancellationToken | None = None,
) -> AsyncIterable[dict[str, Any]]:
    """
    Stub for the Dynamic Workflow Engine stream.
    This will eventually use PTC to generate a Python script that orchestrates sub-agents.
    """
    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "in_progress",
        "data": {"message": "Initializing Dynamic Workflow Engine..."},
    }

    await asyncio.sleep(1)

    yield {
        "type": "status",
        "step_key": "workflow_init",
        "status": "success",
        "data": {"message": "Engine initialized."},
    }

    yield {
        "type": "status",
        "step_key": "workflow_planning",
        "status": "in_progress",
        "data": {"message": "Generating orchestration script..."},
    }

    await asyncio.sleep(1.5)

    yield {
        "type": "status",
        "step_key": "workflow_planning",
        "status": "success",
        "data": {"message": "Orchestration script generated."},
    }

    yield {
        "type": "status",
        "step_key": "workflow_execution",
        "status": "in_progress",
        "data": {"message": "Executing workflow (spawning sub-agents)..."},
    }

    await asyncio.sleep(2)

    yield {
        "type": "status",
        "step_key": "workflow_execution",
        "status": "success",
        "data": {"message": "Workflow execution completed."},
    }

    # Final answer
    yield {
        "type": "content",
        "content": "This is a placeholder response from the Dynamic Workflow Engine. The actual engine will generate a Python script to orchestrate multiple sub-agents concurrently, with SQLite-based event sourcing for durable execution.",
    }

    yield {
        "type": "done",
    }
