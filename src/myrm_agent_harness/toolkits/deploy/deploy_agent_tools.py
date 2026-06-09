"""Agent tool for artifact deployment to hosting platforms.

Single ``deploy_artifact`` tool that handles preflight checks,
HITL approval via LangGraph interrupt, and deployment execution.

The harness defines a ``DeployBackend`` Protocol that the business layer
must implement, keeping the framework decoupled from Vercel or any
specific hosting provider.

[INPUT]
- (none)

[OUTPUT]
- DeployBackend: Protocol that business layer implements
- DeployResult: Typed result returned by the backend
- create_deploy_tool: Factory that produces a single BaseTool

[POS]
Agent tool for deploying artifacts to hosting platforms.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployResult:
    """Structured result from a deployment attempt."""

    success: bool
    url: str
    deployment_id: str
    project_id: str
    status: str
    error: str | None = None


@runtime_checkable
class DeployBackend(Protocol):
    """Protocol that the business layer implements to handle actual deployment.

    The harness only defines the contract; ``myrm-agent-server`` provides
    the concrete implementation that calls VercelClient, resolves tokens,
    runs preflight, etc.
    """

    async def preflight(self, artifact_id: str) -> tuple[bool, str]:
        """Check if an artifact can be deployed.

        Returns:
            (deployable, message) — ``deployable`` is True if ready,
            ``message`` explains why not when False.
        """
        ...

    async def execute_deploy(self, artifact_id: str) -> DeployResult:
        """Execute the deployment for the given artifact.

        The implementation is responsible for:
        - Resolving the Vercel token (stored/platform)
        - Collecting artifact files
        - Calling the Vercel API
        - Persisting deployment state on the Artifact model

        Raises:
            Exception: On deployment failure.
        """
        ...

    async def get_artifact_name(self, artifact_id: str) -> str | None:
        """Return a human-readable name for the artifact, or None if not found."""
        ...


def create_deploy_tool(backend: DeployBackend) -> list[BaseTool]:
    """Create the artifact deploy tool bound to a deployment backend.

    The tool uses LangGraph ``interrupt`` to pause execution and request
    human approval before deploying, matching the pattern used by
    ``ask_question_tool``.

    Returns a single-element list for consistency with other toolkit
    factory functions (e.g. ``create_cron_tools``).
    """

    @tool("deploy_artifact")
    async def deploy_artifact(artifact_id: str) -> str:
        """Deploy an artifact to a hosting platform (currently Vercel).

        Use this tool ONLY when the user explicitly asks to deploy, publish,
        or put an artifact online. Do NOT call this for previewing artifacts.

        The tool will:
        1. Run a preflight check to verify the artifact is deployable.
        2. Request human approval before proceeding (the user must confirm).
        3. Execute the deployment and return the live URL.

        Args:
            artifact_id: The ID of the artifact to deploy. You can find this
                         from the artifact creation response or conversation context.
        """
        artifact_name = await backend.get_artifact_name(artifact_id)
        display_name = artifact_name or artifact_id[:8]

        deployable, preflight_msg = await backend.preflight(artifact_id)
        if not deployable:
            return (
                f"Cannot deploy \"{display_name}\": {preflight_msg}\n\n"
                "If this is a code artifact (React/Vue/etc.), ask the user to "
                "export it as a complete HTML artifact first, then try deploying again."
            )

        from langgraph.types import interrupt

        approval_payload = {
            "type": "deploy_approval",
            "artifact_id": artifact_id,
            "artifact_name": display_name,
            "message": f"Deploy \"{display_name}\" to Vercel?",
        }
        response = interrupt(approval_payload)

        if not response or (isinstance(response, dict) and response.get("decision") == "deny"):
            return f"Deployment of \"{display_name}\" was cancelled by the user."

        try:
            result = await backend.execute_deploy(artifact_id)
        except Exception as exc:
            logger.error("Deployment failed for artifact %s: %s", artifact_id, exc)
            return f"Deployment failed: {exc}"

        if not result.success:
            return f"Deployment failed: {result.error or result.status}"

        return json.dumps(
            {
                "status": "success",
                "url": result.url,
                "deployment_id": result.deployment_id,
                "project_id": result.project_id,
                "message": f"Successfully deployed \"{display_name}\" to {result.url}",
            },
            ensure_ascii=False,
        )

    return [deploy_artifact]
