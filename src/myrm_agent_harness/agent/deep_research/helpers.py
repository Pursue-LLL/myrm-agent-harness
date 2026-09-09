"""Deep Research helper functions — pure utilities for the orchestrator.

[INPUT]
- config::DeepResearchConfig (POS: configuration)
- agent.types::SubagentConfig (POS: subagent config type)
- langchain_core (POS: BaseChatModel, messages)
- toolkits.memory.working_tree.models::EvidenceNode (POS: 强类型树状工作记忆原子节点)
- toolkits.memory.working_tree.tree::EvidenceTree (POS: ReTree 拓扑证据树容器)

[OUTPUT]
- DeepResearchResult: result container dataclass
- CitationAuditResult: citation verification result
- Helper functions: context limit, usage tracking, cost estimation,
  reasoning model detection, tool call extraction, message compaction,
  text truncation, subagent config building, source formatting,
  citation auditing, evidence node creation, format_research_context

[POS]
Stateless helper functions for Deep Research orchestration —
token counting, content formatting, and configuration utilities.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.agent.streaming.citation_audit import CitationAuditResult, audit_citation_markers
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit as get_model_context_limit
from myrm_agent_harness.toolkits.memory.working_tree import (
    BoundedSummary,
    EvidenceNode,
    EvidenceNodeStatus,
    EvidenceSource,
    EvidenceTree,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .config import DeepResearchConfig
from .prompts import RESEARCH_AGENT_PROMPT

logger = get_agent_logger(__name__)

audit_citations = audit_citation_markers


@dataclass
class DeepResearchResult:
    """Container for deep research output."""

    report: str = ""
    research_plan: str = ""
    local_context: str = ""
    cycle_count: int = 0
    total_duration_seconds: float = 0.0
    agent_results: list[dict[str, object]] = field(default_factory=list)
    was_cancelled: bool = False
    error: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    citation_audit: CitationAuditResult | None = None
    evidence_tree: dict[str, object] | None = None


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
        if isinstance(msg, ToolMessage) and len(content_str) > 300:
            first_chunk = content_str.strip().split("\n")[0][:180]
            messages[i] = ToolMessage(
                content=f"[Earlier research result compacted to save context: {first_chunk}...] (full evidence preserved in working tree)",
                tool_call_id=msg.tool_call_id,
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


# ---------------------------------------------------------------------------
# Citation helpers
# ---------------------------------------------------------------------------

_SOURCE_SNIPPET_BUDGET = 200


def format_numbered_sources(sources: list[dict[str, object]], char_budget: int = 8000) -> str:
    """Format sources into a numbered text block for injection into the report prompt.

    Each entry: ``[N] title - url\\nsnippet…``
    Respects *char_budget* to avoid token explosion when source count is high.
    """
    if not sources:
        return ""

    parts: list[str] = []
    used = 0
    for src in sources:
        idx = src.get("index", 0)
        title = str(src.get("title", "")).strip() or "Untitled"
        url = str(src.get("url", "")).strip()
        snippet = str(src.get("snippet", "")).strip()
        if len(snippet) > _SOURCE_SNIPPET_BUDGET:
            snippet = snippet[:_SOURCE_SNIPPET_BUDGET] + "…"

        entry = f"[{idx}] {title}"
        if url:
            entry += f" - {url}"
        if snippet:
            entry += f"\n{snippet}"

        cost = len(entry) + 2
        if used + cost > char_budget and parts:
            parts.append(f"[… {len(sources) - len(parts)} more sources omitted]")
            break
        parts.append(entry)
        used += cost

    return "\n\n".join(parts)


_TASK_COMMON_STOPWORDS: frozenset[str] = frozenset(
    {
        "analysis",
        "market",
        "report",
        "overview",
        "status",
        "strategy",
        "research",
        "global",
        "latest",
        "trend",
        "trends",
        "share",
        "shares",
        "price",
        "pricing",
        "industry",
        "forecast",
        "growth",
        "demand",
        "supply",
        "evaluation",
        "comparison",
    }
)


def create_evidence_node_from_task_result(
    cycle: int,
    task_idx: int,
    task_text: str,
    result_text: str,
    existing_nodes: list[EvidenceNode] | None = None,
) -> EvidenceNode:
    """Construct an EvidenceNode with bounded summary, entity-derived dependencies, and SHA-256 fingerprint."""
    first_line = result_text.strip().split("\n")[0][:180]
    url_match = re.search(r"https?://[^\s)\]]+", result_text)
    source_url = url_match.group(0) if url_match else ""
    content_hash = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).isoformat()

    extracted_entities = [
        w
        for w in re.findall(r"\b[A-Za-z0-9_-]{4,}\b", task_text)
        if w.lower() not in _TASK_COMMON_STOPWORDS
    ][:5]
    summary = BoundedSummary(
        summary=first_line,
        key_entities=extracted_entities,
        key_metrics={},
        estimated_tokens=len(first_line) // 4,
    )
    source = EvidenceSource(
        url=source_url,
        snippet=result_text[:400],
        content_hash=content_hash,
    )

    # Derive causal dependencies from overlapping entities in active nodes
    dependencies: list[str] = []
    if existing_nodes:
        cand_words = {e.lower() for e in extracted_entities}
        for prior_node in existing_nodes:
            if prior_node.node_id == "root_plan":
                continue
            prior_words = {e.lower() for e in prior_node.bounded_summary.key_entities}
            if cand_words.intersection(prior_words):
                dependencies.append(prior_node.node_id)

    if not dependencies:
        dependencies = ["root_plan"]

    return EvidenceNode(
        node_id=f"ev_c{cycle}_{task_idx}",
        claim=task_text,
        bounded_summary=summary,
        source=source,
        dependencies=dependencies,
        dependents=[],
        created_at=now,
        updated_at=now,
    )


def format_research_context(
    agent_results: list[dict[str, object]],
    max_chars: int,
    evidence_tree_data: dict[str, object] | None = None,
) -> str:
    """Format research agent results and verified tree working memory into a single context block.

    Filters out tasks invalidated by the causal evidence tree and prepends
    the verified consensus slice while respecting max_chars budget.
    """
    if not agent_results:
        return ""

    pruned_claims: set[str] = set()
    pruned_hashes: set[str] = set()
    tree_slice = ""

    if evidence_tree_data:
        try:
            tree = EvidenceTree.from_dict(evidence_tree_data)
            for node in tree.nodes.values():
                if node.status == EvidenceNodeStatus.PRUNED_INVALIDATED:
                    pruned_claims.add(node.claim.strip().lower())
                    if node.source.content_hash:
                        pruned_hashes.add(node.source.content_hash)
            tree_slice = tree.format_bounded_slice()
        except Exception:
            logger.warning("[deep-research] Failed to parse evidence tree for report context", exc_info=True)

    separator = "\n\n---\n\n"
    parts: list[str] = []

    if tree_slice:
        parts.append(tree_slice)

    task_counter = 1
    for entry in agent_results:
        task = str(entry.get("task", "Unknown task"))
        result = str(entry.get("result", "No result"))
        res_hash = hashlib.sha256(result.encode("utf-8")).hexdigest()

        if task.strip().lower() in pruned_claims or res_hash in pruned_hashes:
            logger.info("[deep-research] Excluded pruned task from final context: %s", task)
            continue

        parts.append(f"## Research Task {task_counter}: {task}\n\n{result}")
        task_counter += 1

    full = separator.join(parts)
    if len(full) <= max_chars:
        return full

    kept: list[str] = []
    budget = max_chars

    if tree_slice and parts and parts[0] == tree_slice:
        # Guarantee minimum quota for raw task results to prevent empty/hollow reports
        min_body_quota = min(int(max_chars * 0.4), 2000)
        max_tree_chars = max_chars - min_body_quota - len(separator)
        effective_tree_slice = parts[0]
        if max_tree_chars > 200 and len(effective_tree_slice) > max_tree_chars:
            effective_tree_slice = (
                effective_tree_slice[: max_tree_chars - 60]
                + "\n... [Tree slice truncated for report body quota]"
            )
        kept.append(effective_tree_slice)
        budget -= len(effective_tree_slice) + len(separator)
        remaining_parts = parts[1:]
    else:
        remaining_parts = parts

    for part in reversed(remaining_parts):
        cost = len(part) + len(separator)
        if budget >= cost:
            kept.append(part)
            budget -= cost
        elif budget > len(separator) + 100:
            trunc = part[: budget - len(separator) - 50]
            trunc += "\n\n[Truncated — prioritizing most recent research]"
            kept.append(trunc)
            break
        else:
            break

    if tree_slice and parts and parts[0] == tree_slice:
        rest = kept[1:]
        rest.reverse()
        final_parts = [kept[0], *rest]
    else:
        kept.reverse()
        final_parts = kept

    logger.info(
        "[deep-research] Report context: %d items kept, %d/%d chars",
        len(final_parts),
        len(separator.join(final_parts)),
        len(full),
    )
    return separator.join(final_parts)


