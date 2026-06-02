"""Commit Stage Tool - Agent-Driven Context Consolidation.

Gives the Agent the ability to proactively truncate context and generate a phase summary.
Built-in throttle mechanism prevents cache thrashing from frequent LLM calls.

[INPUT]
- (none)

[OUTPUT]
- CommitStageSchema: Schema for commit_stage tool.
- create_commit_stage_tool: Create the commit_stage tool.

[POS]
Commit Stage Tool - Agent-Driven Context Consolidation.
"""

from typing import Any, cast

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

# 防抖阈值：距离上次清零或任务开始必须至少经过这么多 tokens
COMMIT_STAGE_MIN_TOKENS_THROTTLE = 5000


class CommitStageSchema(BaseModel):
    """Schema for commit_stage tool."""

    stage_summary: str = Field(
        ...,
        description="The comprehensive summary of the work completed in this stage. Include key findings, decisions made, and files modified.",
    )
    next_stage_plan: str = Field(..., description="The concrete plan and next steps for the upcoming stage.")
    active_task: str = Field(
        ...,
        description="The overarching user goal or task that you are currently trying to accomplish. Copy this verbatim if possible.",
    )
    unresolved_issues: list[str] = Field(
        default_factory=list,
        description="Any outstanding problems, constraints, or blocked items that need to be addressed in the next stage.",
    )


def create_commit_stage_tool(agent_instance: Any = None) -> BaseTool:
    """Create the commit_stage tool.

    Args:
        agent_instance: The parent agent instance, used to inspect token metrics
                        and inject the `active_stage_commit_flag` into its `_last_context`.

    Returns:
        A LangChain tool that the agent can call to actively consolidate its context.
    """

    @tool("commit_stage_tool", args_schema=CommitStageSchema)
    def commit_stage_tool(
        stage_summary: str, next_stage_plan: str, active_task: str, unresolved_issues: list[str]
    ) -> str:
        """Use this tool when you have completed a significant, distinct phase of a complex, multi-step task and want to proactively consolidate your memory to stay focused and avoid context overload.

        DO NOT use this tool frequently. Only use it when the current context is cluttered with many tool calls (e.g., after >10 bash iterations or >5000 tokens of trial and error).
        When called successfully, the system will archive the raw history and replace it with your provided summary, allowing you to start the next phase with a clean slate.
        """
        if agent_instance is None:
            # If no agent instance is bound, we can't enforce throttling or set the flag.
            # Fail gracefully.
            return "Error: This tool is not properly bound to the agent instance. Cannot commit stage."

        # Check throttle based on agent statistics
        stats = getattr(agent_instance, "_last_run_stats", None)
        parent_c = getattr(agent_instance, "_last_context", None)

        current_tokens = 0
        if parent_c and isinstance(parent_c, dict):
            # Try to get total session tokens from context if available
            current_tokens = parent_c.get("session_total_tokens", 0)

        if current_tokens == 0 and stats is not None and stats.token_usage:
            # Fallback to run stats if session tokens not tracked
            current_tokens = stats.token_usage.total_tokens

        last_commit_tokens = getattr(agent_instance, "_last_stage_commit_tokens", 0)
        tokens_since_commit = current_tokens - last_commit_tokens

        # If current_tokens is 0, we don't have token tracking, so we skip throttle
        if tokens_since_commit < COMMIT_STAGE_MIN_TOKENS_THROTTLE and current_tokens > 0:
            logger.warning(
                " [commit_stage] Throttled: Agent attempted to commit stage too early (%d / %d tokens).",
                tokens_since_commit,
                COMMIT_STAGE_MIN_TOKENS_THROTTLE,
            )
            return (
                f"Throttled: Context is still fresh (only {tokens_since_commit} tokens since last commit/start). "
                f"Please continue working and accumulating more context before committing the stage. "
                "Focus on making progress on the actual task instead."
            )

        # Update the baseline to the current token count to reset the throttle
        agent_instance._last_stage_commit_tokens = current_tokens

        # Inject the explicit semantic boundary signal into the agent's context
        # This will be picked up by ContextPipelineMiddleware to set force_proactive_reset=True
        parent_c = getattr(agent_instance, "_last_context", None)
        if isinstance(parent_c, dict):
            parent_c["active_stage_commit_flag"] = True

            # Optionally pass the generated summary hints into the context so the pipeline can use them
            # (If the SummarizeProcessor wants to incorporate the agent's self-reflection)
            parent_c["active_stage_summary_hint"] = {
                "stage_summary": stage_summary,
                "next_stage_plan": next_stage_plan,
                "active_task": active_task,
                "unresolved_issues": unresolved_issues,
            }
            logger.info(" [commit_stage] Tool execution accepted. Semantic boundary flag injected.")
            return (
                "Success: Your context has been flagged for consolidation. "
                "The system will archive the raw history before your next LLM call and preserve your summary. "
                "You may now proceed with the next_stage_plan."
            )
        else:
            logger.error(" [commit_stage] Could not inject flag because parent _last_context is not a dict.")
            return "Error: System failure. Could not inject consolidation flag."

    return cast(BaseTool, commit_stage_tool)
