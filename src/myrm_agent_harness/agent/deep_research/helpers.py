"""Deep Research helper functions — pure utilities for the orchestrator.

[INPUT]
- config::DeepResearchConfig (POS: configuration)
- agent.types::SubagentConfig (POS: subagent config type)
- langchain_core (POS: BaseChatModel, messages)

[OUTPUT]
- DeepResearchResult: result container dataclass
- Helper functions: context limit, usage tracking, cost estimation,
  reasoning model detection, tool call extraction, message compaction,
  text truncation, subagent config building

[POS]
Stateless helper functions for Deep Research orchestration —
token counting, content formatting, and configuration utilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit as get_model_context_limit
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .config import DeepResearchConfig
from .prompts import RESEARCH_AGENT_PROMPT

logger = get_agent_logger(__name__)


@dataclass
class DeepResearchResult:
    """Container for deep research output."""

    report: str = ""
    research_plan: str = ""
    cycle_count: int = 0
    total_duration_seconds: float = 0.0
    agent_results: list[dict[str, object]] = field(default_factory=list)
    was_cancelled: bool = False
    error: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def get_datetime_str() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def accumulate_usage(result: DeepResearchResult, response: BaseMessage) -> None:
    """Extract and accumulate token usage from an LLM response."""
    usage = getattr(response, "usage_metadata", None)
    if not usage or not isinstance(usage, dict):
        return
    result.total_input_tokens += usage.get("input_tokens", 0)
    result.total_output_tokens += usage.get("output_tokens", 0)


def estimate_cost(result: DeepResearchResult, model_name: str) -> None:
    """Best-effort cost estimation using litellm."""
    if not model_name or (result.total_input_tokens == 0 and result.total_output_tokens == 0):
        return
    try:
        import litellm

        input_cost, output_cost = litellm.cost_per_token(
            model=model_name, prompt_tokens=result.total_input_tokens, completion_tokens=result.total_output_tokens
        )
        result.estimated_cost_usd = input_cost + output_cost
    except Exception:
        pass


def detect_reasoning_model(llm: BaseChatModel) -> bool:
    """Heuristic to detect if the LLM supports native reasoning/thinking."""
    model_name = getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
    model_lower = model_name.lower()
    return any(keyword in model_lower for keyword in ("o1", "o3", "o4", "deepseek-r", "claude-3-7"))


def build_research_subagent_config(config: DeepResearchConfig) -> SubagentConfig:
    """Build SubagentConfig for a research sub-agent."""
    return SubagentConfig(
        system_prompt=RESEARCH_AGENT_PROMPT.format(current_datetime=get_datetime_str()),
        timeout_seconds=config.research_agent_timeout_seconds,
        max_turns=config.max_research_agent_turns,
        max_retries=1,
        max_spawn_depth=0,
        concurrency_limit=config.max_concurrent_agents,
    )


ORCHESTRATOR_RESULT_CHAR_LIMIT = 12_000
MAX_EMPTY_ITERATIONS = 3
_ORCH_CONTEXT_CHAR_BUDGET = 200_000
_ORCH_KEEP_RECENT_MESSAGES = 12


def truncate_for_orchestrator(text: str) -> str:
    """Truncate research result to fit within orchestrator context window."""
    if len(text) <= ORCHESTRATOR_RESULT_CHAR_LIMIT:
        return text
    return text[:ORCHESTRATOR_RESULT_CHAR_LIMIT] + "\n\n[Truncated — full result available in report context]"


def compact_orch_messages(messages: list[BaseMessage]) -> None:
    """Compact orchestrator messages in-place when context exceeds budget.

    Preserves: system prompt (index 0) and the most recent messages.
    Middle ToolMessage results are replaced with short summaries.
    """
    total_chars = sum(len(str(m.content)) for m in messages)
    if total_chars <= _ORCH_CONTEXT_CHAR_BUDGET:
        return

    keep_start = 1
    keep_end = max(keep_start, len(messages) - _ORCH_KEEP_RECENT_MESSAGES)

    compacted = 0
    for i in range(keep_start, keep_end):
        msg = messages[i]
        content_str = str(msg.content)
        if isinstance(msg, ToolMessage) and len(content_str) > 200:
            messages[i] = ToolMessage(
                content="[Earlier research result compacted to save context]", tool_call_id=msg.tool_call_id
            )
            compacted += 1

    if compacted:
        new_total = sum(len(str(m.content)) for m in messages)
        logger.info("[deep-research] Compacted %d messages: %d→%d chars", compacted, total_chars, new_total)


def extract_tool_calls(response: AIMessage) -> list[dict[str, object]]:
    """Extract tool calls from AIMessage, handling both formats."""
    if hasattr(response, "tool_calls") and response.tool_calls:
        return [
            {
                "id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            }
            for tc in response.tool_calls
        ]
    return []
