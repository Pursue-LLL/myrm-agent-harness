"""A2A delegation and orchestration agent tools.

Provides `a2a_call` for targeted single-peer task delegation and
`a2a_orchestrate` for multi-peer capability fan-out with configurable
aggregation policies ('all', 'first', 'best').

[INPUT]
- peer_url / peers, prompt, capability, mode

[OUTPUT]
- Structured delegation results and synthesized multi-agent findings

[POS]
Harness-level tools enabling autonomous agents to invoke remote A2A nodes.
"""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.a2a.client import (
    A2AClient,
    A2AClientError,
    A2ASSRFBlockedError,
)
from myrm_agent_harness.toolkits.a2a.types import A2ATask, TaskStatus

logger = logging.getLogger(__name__)


class FanoutMode(StrEnum):
    """Aggregation mode for A2A multi-peer orchestration."""

    ALL = "all"
    FIRST = "first"
    BEST = "best"


class A2ACallInput(BaseModel):
    """Input arguments for a2a_call tool."""

    peer_url: str = Field(
        description="Remote A2A endpoint URL (e.g. http://peer:8080/api/v1/a2a/rpc)"
    )
    prompt: str = Field(
        description="The task instruction or query to send to the remote agent."
    )
    agent_id: str | None = Field(
        default=None, description="Optional target remote agent profile ID."
    )
    bearer_token: str | None = Field(
        default=None, description="Optional authentication Bearer token."
    )
    timeout_seconds: float = Field(
        default=60.0, description="Maximum wait time in seconds."
    )


class A2AOrchestrateInput(BaseModel):
    """Input arguments for a2a_orchestrate tool."""

    peers: list[str] = Field(description="List of remote peer A2A endpoint URLs.")
    prompt: str = Field(description="Task instruction broadcast to all peer agents.")
    mode: FanoutMode = Field(
        default=FanoutMode.ALL,
        description="Aggregation strategy: 'all' (gather all), 'first' (fastest success), 'best' (highest detail).",
    )
    timeout_seconds: float = Field(
        default=90.0, description="Overall fan-out timeout in seconds."
    )


async def execute_a2a_call(
    peer_url: str,
    prompt: str,
    *,
    agent_id: str | None = None,
    bearer_token: str | None = None,
    timeout_seconds: float = 60.0,
    client: A2AClient | None = None,
) -> dict[str, object]:
    """Execute a single remote A2A task delegation."""
    a2a_client = client or A2AClient(timeout_seconds=timeout_seconds)
    try:
        task = await a2a_client.send_task(
            peer_url,
            prompt,
            agent_id=agent_id,
            bearer_token=bearer_token,
            timeout_sec=timeout_seconds,
        )

        # Wait for terminal state
        completed_task = await a2a_client.wait_for_completion(
            peer_url,
            task.task_id,
            bearer_token=bearer_token,
            max_wait_sec=timeout_seconds,
        )

        agent_messages = [
            m.content for m in completed_task.messages if m.role == "agent"
        ]
        final_answer = agent_messages[-1] if agent_messages else ""

        return {
            "success": completed_task.status == TaskStatus.COMPLETED,
            "status": completed_task.status.value,
            "taskId": completed_task.task_id,
            "answer": final_answer,
            "artifacts": [
                a.model_dump(by_alias=True) for a in completed_task.artifacts
            ],
            "error": completed_task.error,
        }
    except A2ASSRFBlockedError as e:
        return {
            "success": False,
            "status": "blocked",
            "error": f"Security policy blocked URL: {e}",
        }
    except Exception as e:
        logger.warning("a2a_call to %s failed: %s", peer_url, e)
        return {"success": False, "status": "error", "error": str(e)}


async def execute_a2a_orchestrate(
    peers: list[str],
    prompt: str,
    *,
    mode: FanoutMode = FanoutMode.ALL,
    timeout_seconds: float = 90.0,
    client: A2AClient | None = None,
) -> dict[str, object]:
    """Execute multi-peer capability fan-out orchestration."""
    if not peers:
        return {
            "success": False,
            "mode": mode.value,
            "error": "Peers list cannot be empty.",
        }

    a2a_client = client or A2AClient(timeout_seconds=timeout_seconds)

    async def _call_single(p_url: str) -> dict[str, object]:
        res = await execute_a2a_call(
            p_url,
            prompt,
            timeout_seconds=timeout_seconds,
            client=a2a_client,
        )
        res["peer"] = p_url
        return res

    if mode == FanoutMode.FIRST:
        tasks = [asyncio.create_task(_call_single(p)) for p in peers]
        first_success: dict[str, object] | None = None
        errors: list[str] = []

        for coro in asyncio.as_completed(tasks):
            try:
                res = await coro
                if res.get("success") is True:
                    first_success = res
                    break
                else:
                    errors.append(str(res.get("error") or "failed"))
            except Exception as e:
                errors.append(str(e))

        # Cancel remaining
        for t in tasks:
            if not t.done():
                t.cancel()

        if first_success is not None:
            return {"success": True, "mode": "first", "result": first_success}
        return {
            "success": False,
            "mode": "first",
            "error": "All peers failed",
            "details": errors,
        }

    # FanoutMode.ALL or FanoutMode.BEST
    results = await asyncio.gather(
        *[_call_single(p) for p in peers], return_exceptions=False
    )
    successful = [r for r in results if r.get("success") is True]

    if mode == FanoutMode.BEST:
        if not successful:
            return {
                "success": False,
                "mode": "best",
                "error": "No peer returned successful answer",
                "results": results,
            }
        # Best strategy: rank by answer length and richness of artifacts
        best_result = max(
            successful,
            key=lambda x: len(str(x.get("answer") or "")) + 200 * len(x.get("artifacts") or []),  # type: ignore
        )
        return {
            "success": True,
            "mode": "best",
            "best": best_result,
            "total_peers": len(peers),
        }

    # Default 'all'
    return {
        "success": len(successful) > 0,
        "mode": "all",
        "total_peers": len(peers),
        "successful_count": len(successful),
        "results": results,
    }
