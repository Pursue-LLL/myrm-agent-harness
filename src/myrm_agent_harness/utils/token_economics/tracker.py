"""Token 使用量追踪器

1. 本文件的 INPUT/OUTPUT/POS 注释
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §6.3 缓存可观测性

[INPUT]
- contextvars::ContextVar (POS: Python 标准库，提供上下文变量隔离)
- .cost_engine::compute_cost (POS: 成本计算引擎，封装 litellm.completion_cost + CostStatus 溯源)
- .cache_economics::compute_prompt_cache_stats (POS: 缓存命中率与相对未缓存 input 的节省比例)
- .usage_ledger::UsageRecord (POS: 审计日志记录类型，lazy import)
- .budget_guard::BudgetChecker (POS: Budget guard protocol, TYPE_CHECKING only)

[OUTPUT]
- TokenUsage: Token 使用量统计类（prompt/completion/total/cached/cache_write/reasoning/citation tokens + input/output/net_input aliases）
  - get_cache_effectiveness(): 会话级缓存效果
- LatencyStats: 延迟统计 frozen dataclass（avg_ms, p95_ms, min_ms, max_ms, avg_ttft_ms, p95_ttft_ms, avg_tokens_per_second）
- TokenTracker: Token 追踪器类（token 使用量、模型级费用、工具级归因、成本溯源、延迟、错误）
- init_token_tracker(): 初始化请求级 token 追踪器
- get_token_tracker(): 获取当前请求的 token 追踪器
- reset_token_tracker(): 重置 token 追踪器
- record_token_usage(): 记录 token 使用量（含 model、duration、cost、cost_status）
- push_tool_context() / pop_tool_context(): 工具归因栈操作
- record_token_error(): 记录 LLM 调用失败
- record_finish_reason(): 记录 LLM 调用的 finish_reason
- get_pending_token_events(): 获取待发送的 token 事件（实时推送）
- append_to_ledger(): 追加使用记录到审计日志（供流式回调和适配器调用）

[POS]
LLM call metadata tracker. ContextVar-based request-level tracking supporting both streaming and non-streaming modes.

"""

import logging
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.coercion import parse_int

from .cache_economics import compute_prompt_cache_stats

if TYPE_CHECKING:
    from .budget_guard import BudgetChecker

logger = logging.getLogger(__name__)

_MAX_DURATION_SAMPLES = 1000
_TRIM_TO_SIZE = 500


def _trim_list(data: list[float]) -> None:
    """Trim list to prevent unbounded growth, keeping most recent samples."""
    if len(data) >= _MAX_DURATION_SAMPLES:
        del data[: len(data) - _TRIM_TO_SIZE + 1]


def _percentile(sorted_data: list[float], p: float) -> float:
    """Compute percentile from sorted data."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


_TOKEN_USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "citation_tokens",
)


@dataclass
class TokenUsage:
    """Token usage statistics.

    Fields follow LiteLLM/OpenAI convention:
    - prompt_tokens INCLUDES cached_tokens (total input billed by provider)
    - cached_tokens is the portion served from cache
    - cache_write_tokens is newly written to cache (Anthropic)
    - citation_tokens is tokens consumed by inline citations (Perplexity/OpenAI)

    Semantic aliases (properties):
    - input_tokens  → prompt_tokens  (readable synonym)
    - output_tokens → completion_tokens
    - net_input_tokens → prompt_tokens - cached_tokens (actual "new" input)
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    citation_tokens: int = 0
    last_call: "TokenUsage | None" = field(default=None, repr=False)

    # --- Semantic aliases ---

    @property
    def input_tokens(self) -> int:
        return self.prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.completion_tokens

    @property
    def net_input_tokens(self) -> int:
        """Tokens that were actually computed (not served from cache)."""
        return max(self.prompt_tokens - self.cached_tokens, 0)

    # --- Accumulation ---

    def add(self, usage: Mapping[str, object]) -> None:
        """Accumulate token usage from a single LLM call, updating last_call snapshot."""
        call_prompt = parse_int(usage.get("prompt_tokens"), 0, min_val=0)
        call_completion = parse_int(usage.get("completion_tokens"), 0, min_val=0)
        call_total = parse_int(usage.get("total_tokens"), 0, min_val=0)
        call_cached = self._extract_cached(usage)
        call_cache_write = self._extract_cache_write(usage)
        call_reasoning = self._extract_reasoning(usage)
        call_citation = self._extract_citation(usage)

        self.prompt_tokens += call_prompt
        self.completion_tokens += call_completion
        self.total_tokens += call_total
        self.cached_tokens += call_cached
        self.cache_write_tokens += call_cache_write
        self.reasoning_tokens += call_reasoning
        self.citation_tokens += call_citation

        self.last_call = TokenUsage(
            prompt_tokens=call_prompt,
            completion_tokens=call_completion,
            total_tokens=call_total,
            cached_tokens=call_cached,
            cache_write_tokens=call_cache_write,
            reasoning_tokens=call_reasoning,
            citation_tokens=call_citation,
        )

    # --- Provider field extraction ---

    def _extract_cached(self, usage: Mapping[str, object]) -> int:
        """Extract cached_tokens — LiteLLM normalizes to prompt_tokens_details.cached_tokens."""
        prompt_details = usage.get("prompt_tokens_details", {})
        if isinstance(prompt_details, dict):
            return parse_int(prompt_details.get("cached_tokens"), 0, min_val=0)
        return 0

    def _extract_cache_write(self, usage: Mapping[str, object]) -> int:
        """Extract cache_write_tokens (Anthropic cache_creation_input_tokens)."""
        direct = usage.get("cache_creation_input_tokens")
        if direct is not None:
            return parse_int(direct, 0, min_val=0)
        prompt_details = usage.get("prompt_tokens_details", {})
        if isinstance(prompt_details, dict):
            return parse_int(prompt_details.get("cache_creation_input_tokens"), 0, min_val=0)
        return 0

    def _extract_reasoning(self, usage: Mapping[str, object]) -> int:
        """Extract reasoning_tokens from completion_tokens_details or top-level."""
        comp_details = usage.get("completion_tokens_details", {})
        if isinstance(comp_details, dict):
            val = parse_int(comp_details.get("reasoning_tokens"), 0, min_val=0)
            if val:
                return val
        return parse_int(usage.get("reasoning_tokens"), 0, min_val=0)

    def _extract_citation(self, usage: Mapping[str, object]) -> int:
        """Extract citation_tokens (Perplexity/OpenAI prompt_tokens_details.citation_tokens)."""
        prompt_details = usage.get("prompt_tokens_details", {})
        if isinstance(prompt_details, dict):
            val = parse_int(prompt_details.get("citation_tokens"), 0, min_val=0)
            if val:
                return val
        return parse_int(usage.get("citation_tokens"), 0, min_val=0)

    # --- Serialization ---

    def to_dict(self) -> dict[str, int]:
        """Serialize to dict for SSE/DB/frontend."""
        return {f: getattr(self, f) for f in _TOKEN_USAGE_FIELDS}

    def get_cache_effectiveness(self, cache_read_ratio: float = 0.1) -> dict[str, float]:
        """Compute session-level cache effectiveness.

        Args:
            cache_read_ratio: Cache-read cost as fraction of base input cost.
                Anthropic: 0.1 (90% off), OpenAI: 0.5 (50% off)
        """
        return compute_prompt_cache_stats(self.prompt_tokens, self.cached_tokens, cache_read_ratio=cache_read_ratio)


@dataclass(frozen=True)
class LatencyStats:
    """LLM 调用延迟统计"""

    call_count: int = 0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ttft_ms: float = 0.0
    p95_ttft_ms: float = 0.0
    avg_tokens_per_second: float = 0.0


# ---------------------------------------------------------------------------
# TokenTracker
# ---------------------------------------------------------------------------


@dataclass
class TokenTracker:
    """Request-scoped LLM call tracker: tokens, cost, latency, TTFT, errors."""

    usage: TokenUsage = field(default_factory=TokenUsage)
    call_count: int = 0
    pending_events: list[dict[str, object]] = field(default_factory=list)
    last_finish_reason: str | None = None

    model_usage: dict[str, TokenUsage] = field(default_factory=dict)
    model_cost: dict[str, float] = field(default_factory=dict)
    model_savings: dict[str, float] = field(default_factory=dict)
    tool_stack: list[str] = field(default_factory=list)
    tool_usage: dict[str, TokenUsage] = field(default_factory=dict)
    tool_cost: dict[str, float] = field(default_factory=dict)
    call_durations_ms: list[float] = field(default_factory=list)
    call_ttft_ms: list[float] = field(default_factory=list)
    total_cost_usd: float = 0.0
    total_cache_savings_usd: float = 0.0
    cost_status: str = "unknown"
    error_count: int = 0
    last_error: str | None = None
    budget_checker: "BudgetChecker | None" = field(default=None, repr=False)
    last_budget_status: str = "ok"

    # --- Tool chain tracking ---

    def push_tool(self, tool_name: str) -> None:
        """Push a tool onto the attribution stack."""
        self.tool_stack.append(tool_name)

    def pop_tool(self) -> None:
        """Pop the top tool from the attribution stack (safe on empty)."""
        if self.tool_stack:
            self.tool_stack.pop()

    def record(
        self,
        usage: Mapping[str, object],
        *,
        model_name: str | None = None,
        duration_ms: float | None = None,
        ttft_ms: float | None = None,
        cost_usd: float = 0.0,
        cost_status: str = "unknown",
        cache_savings_usd: float = 0.0,
    ) -> None:
        """Record metadata from a single LLM call."""
        self.usage.add(usage)
        self.call_count += 1

        if model_name:
            if model_name not in self.model_usage:
                self.model_usage[model_name] = TokenUsage()
            self.model_usage[model_name].add(usage)
            self.model_cost[model_name] = self.model_cost.get(model_name, 0.0) + cost_usd
            self.model_savings[model_name] = self.model_savings.get(model_name, 0.0) + cache_savings_usd

        if self.tool_stack:
            active_tool = self.tool_stack[-1]
            if active_tool not in self.tool_usage:
                self.tool_usage[active_tool] = TokenUsage()
            self.tool_usage[active_tool].add(usage)
            self.tool_cost[active_tool] = self.tool_cost.get(active_tool, 0.0) + cost_usd

        if duration_ms is not None:
            _trim_list(self.call_durations_ms)
            self.call_durations_ms.append(duration_ms)

        if ttft_ms is not None:
            _trim_list(self.call_ttft_ms)
            self.call_ttft_ms.append(ttft_ms)

        self.total_cost_usd += cost_usd
        self.total_cache_savings_usd += cache_savings_usd
        if cost_status == "actual" or (self.cost_status == "unknown" and cost_status != "unknown"):
            self.cost_status = cost_status

        if self.budget_checker is not None and cost_usd > 0:
            self.last_budget_status = self.budget_checker.record_cost(cost_usd)

        event: dict[str, object] = {
            "call_index": self.call_count,
            "usage": self.usage.to_dict(),
        }
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        if ttft_ms is not None:
            event["ttft_ms"] = ttft_ms
        if model_name:
            event["model_name"] = model_name
        if cost_usd > 0:
            event["cost_usd"] = round(cost_usd, 6)
        if cache_savings_usd > 0:
            event["cache_savings_usd"] = round(cache_savings_usd, 6)
        self.pending_events.append(event)

    def record_error(self, error_message: str) -> None:
        """记录 LLM 调用失败。"""
        self.error_count += 1
        self.last_error = error_message

    def get_usage(self) -> TokenUsage:
        """获取累积的 token 使用量"""
        return self.usage

    def get_latency_stats(self) -> LatencyStats:
        """计算延迟统计（含 TTFT 和 tokens/s）"""
        if not self.call_durations_ms:
            return LatencyStats()

        sorted_durations = sorted(self.call_durations_ms)
        sorted_ttft = sorted(self.call_ttft_ms) if self.call_ttft_ms else []

        total_duration_s = sum(self.call_durations_ms) / 1000.0
        avg_tps = self.usage.completion_tokens / total_duration_s if total_duration_s > 0 else 0.0

        return LatencyStats(
            call_count=len(sorted_durations),
            avg_ms=sum(sorted_durations) / len(sorted_durations),
            p95_ms=_percentile(sorted_durations, 0.95),
            min_ms=sorted_durations[0],
            max_ms=sorted_durations[-1],
            avg_ttft_ms=(sum(sorted_ttft) / len(sorted_ttft) if sorted_ttft else 0.0),
            p95_ttft_ms=_percentile(sorted_ttft, 0.95),
            avg_tokens_per_second=round(avg_tps, 1),
        )

    def merge(self, other: "TokenTracker") -> None:
        """Merge a child Agent's tracking data into this tracker.

        last_finish_reason is kept from parent (parent is the final conversing Agent).
        """
        for field_name in _TOKEN_USAGE_FIELDS:
            setattr(
                self.usage,
                field_name,
                getattr(self.usage, field_name) + getattr(other.usage, field_name),
            )

        for model, model_usage in other.model_usage.items():
            if model not in self.model_usage:
                self.model_usage[model] = TokenUsage()
            target = self.model_usage[model]
            for f in _TOKEN_USAGE_FIELDS:
                setattr(target, f, getattr(target, f) + getattr(model_usage, f))
            self.model_cost[model] = self.model_cost.get(model, 0.0) + other.model_cost.get(model, 0.0)
            self.model_savings[model] = self.model_savings.get(model, 0.0) + other.model_savings.get(model, 0.0)

        for tool, tool_usage in other.tool_usage.items():
            if tool not in self.tool_usage:
                self.tool_usage[tool] = TokenUsage()
            target = self.tool_usage[tool]
            for f in _TOKEN_USAGE_FIELDS:
                setattr(target, f, getattr(target, f) + getattr(tool_usage, f))
            self.tool_cost[tool] = self.tool_cost.get(tool, 0.0) + other.tool_cost.get(tool, 0.0)

        self.call_durations_ms.extend(other.call_durations_ms)
        self.call_ttft_ms.extend(other.call_ttft_ms)
        self.call_count += other.call_count
        self.total_cost_usd += other.total_cost_usd
        self.total_cache_savings_usd += other.total_cache_savings_usd
        if other.cost_status == "actual" or (self.cost_status == "unknown" and other.cost_status != "unknown"):
            self.cost_status = other.cost_status
        self.error_count += other.error_count

    def get_and_clear_pending_events(self) -> list[dict[str, object]]:
        """获取并清空待发送的事件列表"""
        events = self.pending_events
        self.pending_events = []
        return events

    def to_dict(self) -> dict[str, object]:
        """Export full tracking data for business layer integration."""
        latency = self.get_latency_stats()
        result: dict[str, object] = {
            "usage": self.usage.to_dict(),
            "call_count": self.call_count,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_cache_savings_usd": round(self.total_cache_savings_usd, 6),
            "cost_status": self.cost_status,
            "error_count": self.error_count,
            "latency": {
                "avg_ms": round(latency.avg_ms, 1),
                "p95_ms": round(latency.p95_ms, 1),
                "min_ms": round(latency.min_ms, 1),
                "max_ms": round(latency.max_ms, 1),
                "avg_ttft_ms": round(latency.avg_ttft_ms, 1),
                "p95_ttft_ms": round(latency.p95_ttft_ms, 1),
                "avg_tokens_per_second": latency.avg_tokens_per_second,
            },
        }
        if self.model_usage:
            result["model_breakdown"] = {
                model: {
                    **usage.to_dict(),
                    "cost_usd": round(self.model_cost.get(model, 0.0), 6),
                    "cache_savings_usd": round(self.model_savings.get(model, 0.0), 6),
                }
                for model, usage in self.model_usage.items()
            }
        if self.tool_usage:
            result["tool_breakdown"] = {
                tool: {**usage.to_dict(), "cost_usd": round(self.tool_cost.get(tool, 0.0), 6)}
                for tool, usage in self.tool_usage.items()
            }
        return result


# ---------------------------------------------------------------------------
# ContextVar-based request-scoped API
# ---------------------------------------------------------------------------

_current_tracker: ContextVar[TokenTracker | None] = ContextVar("token_tracker", default=None)
_current_ledger: ContextVar["_UsageLedgerType | None"] = ContextVar("usage_ledger", default=None)

# Avoid circular import; resolved lazily
_UsageLedgerType = object


def init_token_tracker(
    budget_checker: "BudgetChecker | None" = None,
) -> TokenTracker:
    """初始化当前请求的 token 追踪器"""
    tracker = TokenTracker(budget_checker=budget_checker)
    _current_tracker.set(tracker)
    return tracker


def set_usage_ledger(ledger: object) -> None:
    """Attach a UsageLedger to the current request scope.

    Called by business layer (e.g. base_agent) when session_dir is known.
    """
    _current_ledger.set(ledger)


def get_usage_ledger() -> object | None:
    """Get the current request-scoped UsageLedger (if any)."""
    return _current_ledger.get()


def get_token_tracker() -> TokenTracker | None:
    """获取当前请求的 token 追踪器"""
    return _current_tracker.get()


def reset_token_tracker() -> None:
    """重置当前请求的 token 追踪器和 UsageLedger"""
    _current_tracker.set(None)
    _current_ledger.set(None)


def record_token_usage(
    usage: Mapping[str, object],
    *,
    model_name: str | None = None,
    duration_ms: float | None = None,
    ttft_ms: float | None = None,
    cost_usd: float = 0.0,
    cost_status: str = "unknown",
    cache_savings_usd: float = 0.0,
) -> None:
    """Record token usage to the current request-scoped tracker."""
    tracker = _current_tracker.get()
    if tracker:
        tracker.record(
            usage,
            model_name=model_name,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            cost_usd=cost_usd,
            cost_status=cost_status,
            cache_savings_usd=cache_savings_usd,
        )


def push_tool_context(tool_name: str) -> None:
    """Push a tool onto the attribution stack for the current tracker."""
    tracker = _current_tracker.get()
    if tracker:
        tracker.push_tool(tool_name)


def pop_tool_context() -> None:
    """Pop the top tool from the attribution stack for the current tracker."""
    tracker = _current_tracker.get()
    if tracker:
        tracker.pop_tool()


def record_token_error(error_message: str) -> None:
    """Record an LLM call failure to the current tracker."""
    tracker = _current_tracker.get()
    if tracker:
        tracker.record_error(error_message)


def record_finish_reason(reason: str) -> None:
    """记录 LLM 调用的 finish_reason 到当前追踪器

    每次 LLM 调用覆盖前值（last-write-wins），最终值反映最后一次调用的结束原因。
    """
    tracker = _current_tracker.get()
    if tracker:
        tracker.last_finish_reason = reason


def get_pending_token_events() -> list[dict[str, object]]:
    """获取并清空待发送的 token 事件列表"""
    tracker = _current_tracker.get()
    if tracker:
        return tracker.get_and_clear_pending_events()
    return []


# ============================================================================
# LiteLLM 回调集成（lazy import）
# ============================================================================

_TOKEN_TRACKING_CALLBACK_CLASS: type[object] | None = None


def append_to_ledger(
    usage: Mapping[str, object],
    model_name: str | None,
    duration_ms: float | None,
    cost_usd: float,
    cache_savings_usd: float = 0.0,
    ttft_ms: float | None = None,
    finish_reason: str = "",
) -> None:
    """Append a record to the request-scoped UsageLedger (if attached)."""
    ledger = _current_ledger.get()
    if ledger is None:
        return
    try:
        from .usage_ledger import UsageRecord

        tracker = _current_tracker.get()
        call_index = tracker.call_count if tracker else 0

        snapshot = TokenUsage()
        snapshot.add(usage)

        record = UsageRecord(
            model=model_name or "",
            prompt_tokens=snapshot.prompt_tokens,
            completion_tokens=snapshot.completion_tokens,
            total_tokens=snapshot.total_tokens,
            cached_tokens=snapshot.cached_tokens,
            cache_write_tokens=snapshot.cache_write_tokens,
            reasoning_tokens=snapshot.reasoning_tokens,
            citation_tokens=snapshot.citation_tokens,
            cost_usd=cost_usd,
            cache_savings_usd=cache_savings_usd,
            latency_ms=duration_ms or 0.0,
            ttft_ms=ttft_ms or 0.0,
            finish_reason=finish_reason,
            call_index=call_index,
        )
        ledger.append(record)  # type: ignore[union-attr]
    except Exception:
        logger.debug("Failed to append usage record to ledger", exc_info=True)


def _compute_duration_ms(start_time: object, end_time: object) -> float | None:
    """Compute duration in ms from datetime objects."""
    if isinstance(start_time, datetime) and isinstance(end_time, datetime):
        return (end_time - start_time).total_seconds() * 1000.0
    return None


def _get_token_tracking_callback_class() -> type[object]:
    """Create the LiteLLM callback class only when it is actually needed."""
    global _TOKEN_TRACKING_CALLBACK_CLASS
    if _TOKEN_TRACKING_CALLBACK_CLASS is not None:
        return _TOKEN_TRACKING_CALLBACK_CLASS

    import litellm

    class TokenTrackingCallback(litellm.integrations.custom_logger.CustomLogger):
        """LiteLLM callback that records token usage, cost, latency, and errors."""

        def _is_streaming_call(self, kwargs: dict[str, object]) -> bool:
            return kwargs.get("stream", False) is True

        def _extract_usage(self, response_obj: object) -> dict[str, object]:
            if hasattr(response_obj, "usage") and response_obj.usage:
                usage_obj = response_obj.usage
                if hasattr(usage_obj, "model_dump"):
                    return usage_obj.model_dump()
                if isinstance(usage_obj, dict):
                    return usage_obj
                return {
                    "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
                    "total_tokens": getattr(usage_obj, "total_tokens", 0),
                }
            return {}

        def log_success_event(
            self,
            kwargs: dict[str, object],
            response_obj: object,
            start_time: object,
            end_time: object,
        ) -> None:
            if self._is_streaming_call(kwargs):
                return

            usage = self._extract_usage(response_obj)
            if not usage:
                return

            model_name = str(kwargs.get("model", "")) or None
            duration_ms = _compute_duration_ms(start_time, end_time)

            from .cache_savings import calculate_cache_savings_usd
            from .cost_engine import compute_cost

            cost_result = compute_cost(response_obj, model_name)
            cache_savings_usd = calculate_cache_savings_usd(usage, model_name)

            finish_reason = ""
            choices = getattr(response_obj, "choices", None)
            if choices and len(choices) > 0:
                finish_reason = getattr(choices[0], "finish_reason", "") or ""

            record_token_usage(
                usage,
                model_name=model_name,
                duration_ms=duration_ms,
                cost_usd=cost_result.usd,
                cost_status=cost_result.status,
                cache_savings_usd=cache_savings_usd,
            )

            append_to_ledger(
                usage, model_name, duration_ms, cost_result.usd, cache_savings_usd,
                finish_reason=finish_reason,
            )

        async def async_log_success_event(
            self,
            kwargs: dict[str, object],
            response_obj: object,
            start_time: object,
            end_time: object,
        ) -> None:
            self.log_success_event(kwargs, response_obj, start_time, end_time)

        def log_failure_event(
            self,
            kwargs: dict[str, object],
            response_obj: object,
            start_time: object,
            end_time: object,
        ) -> None:
            exception = kwargs.get("exception")
            error_msg = str(exception) if exception else "Unknown LLM error"
            record_token_error(error_msg)

        async def async_log_failure_event(
            self,
            kwargs: dict[str, object],
            response_obj: object,
            start_time: object,
            end_time: object,
        ) -> None:
            self.log_failure_event(kwargs, response_obj, start_time, end_time)

    _TOKEN_TRACKING_CALLBACK_CLASS = TokenTrackingCallback
    return TokenTrackingCallback


def setup_token_tracking_callback() -> None:
    """Set up the LiteLLM callback for token tracking."""
    import litellm

    callback = _get_token_tracking_callback_class()()
    if callback not in litellm.callbacks:
        litellm.callbacks.append(callback)


def __getattr__(name: str) -> object:
    if name == "TokenTrackingCallback":
        value = _get_token_tracking_callback_class()
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
