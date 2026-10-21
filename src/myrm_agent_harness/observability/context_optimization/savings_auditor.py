"""
[INPUT]: Session IDs, tool names, raw payload bytes, optimized bytes, and optional token overrides.
[OUTPUT]: Immutable ToolSavingsRecord entries, per-tool aggregation, and comprehensive SessionSavingsAudit war reports.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/context_optimization/savings_auditor.py
"""

from collections import defaultdict
from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional

from .models import (
    SessionSavingsAudit,
    ToolSavingsRecord,
    ToolSavingsSummary,
)


class ContextOptimizationSavingsAuditor:
    """
    Audits token savings from tool output truncation, stubbing, and prompt cache hits,
    converting raw byte/token metrics into quantified financial and engineering value reports.
    """

    # Baseline cost conversion: $0.003 per 1K input tokens, exchange rate 7.15 CNY/USD
    DEFAULT_USD_PER_1K_TOKENS: float = 0.003
    DEFAULT_CNY_PER_USD: float = 7.15

    def __init__(
        self,
        usd_per_1k_tokens: float = DEFAULT_USD_PER_1K_TOKENS,
        cny_per_usd: float = DEFAULT_CNY_PER_USD,
    ) -> None:
        self._lock = threading.Lock()
        self._usd_rate = usd_per_1k_tokens
        self._cny_rate = cny_per_usd
        # session_id -> list of records
        self._records: Dict[str, List[ToolSavingsRecord]] = defaultdict(list)

    @staticmethod
    def _estimate_tokens_from_bytes(byte_count: int) -> int:
        """Heuristic rule: ~4 bytes per token for mixed English/code/Chinese."""
        return max(1, byte_count // 4)

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        original_bytes: int,
        optimized_bytes: int,
        cache_hit: bool = False,
        explicit_original_tokens: Optional[int] = None,
        explicit_optimized_tokens: Optional[int] = None,
    ) -> ToolSavingsRecord:
        orig_tokens = (
            explicit_original_tokens
            if explicit_original_tokens is not None
            else self._estimate_tokens_from_bytes(original_bytes)
        )
        opt_tokens = (
            explicit_optimized_tokens
            if explicit_optimized_tokens is not None
            else self._estimate_tokens_from_bytes(optimized_bytes)
        )
        saved_tokens = max(0, orig_tokens - opt_tokens)
        savings_rate = (
            round((saved_tokens / max(1, orig_tokens)) * 100.0, 2)
            if orig_tokens > 0
            else 0.0
        )

        cost_saved_usd = round((saved_tokens / 1000.0) * self._usd_rate, 4)
        cost_saved_cny = round(cost_saved_usd * self._cny_rate, 4)

        now_str = datetime.now(timezone.utc).isoformat()
        record = ToolSavingsRecord(
            session_id=session_id,
            tool_name=tool_name,
            original_bytes=original_bytes,
            optimized_bytes=optimized_bytes,
            original_tokens=orig_tokens,
            optimized_tokens=opt_tokens,
            saved_tokens=saved_tokens,
            savings_rate_pct=savings_rate,
            cost_saved_usd=cost_saved_usd,
            cost_saved_cny=cost_saved_cny,
            cache_hit=cache_hit,
            recorded_at=now_str,
        )

        with self._lock:
            self._records[session_id].append(record)

        return record

    def get_session_audit(self, session_id: str) -> SessionSavingsAudit:
        with self._lock:
            records = list(self._records.get(session_id, []))

        if not records:
            return SessionSavingsAudit(
                session_id=session_id,
                total_tool_calls=0,
                total_original_tokens=0,
                total_optimized_tokens=0,
                total_saved_tokens=0,
                overall_savings_rate_pct=0.0,
                total_cost_saved_usd=0.0,
                total_cost_saved_cny=0.0,
                tool_breakdown=[],
                summary_headline="暂无工具拦截节流调用记录",
            )

        total_calls = len(records)
        total_orig = sum(r.original_tokens for r in records)
        total_opt = sum(r.optimized_tokens for r in records)
        total_saved = sum(r.saved_tokens for r in records)
        overall_rate = (
            round((total_saved / max(1, total_orig)) * 100.0, 2)
            if total_orig > 0
            else 0.0
        )
        total_usd = round(sum(r.cost_saved_usd for r in records), 4)
        total_cny = round(sum(r.cost_saved_cny for r in records), 4)

        # Group by tool_name
        grouped: Dict[str, List[ToolSavingsRecord]] = defaultdict(list)
        for r in records:
            grouped[r.tool_name].append(r)

        breakdown: List[ToolSavingsSummary] = []
        for tool, items in grouped.items():
            t_calls = len(items)
            t_orig = sum(i.original_tokens for i in items)
            t_opt = sum(i.optimized_tokens for i in items)
            t_saved = sum(i.saved_tokens for i in items)
            t_rate = round((t_saved / max(1, t_orig)) * 100.0, 2) if t_orig > 0 else 0.0
            t_usd = round(sum(i.cost_saved_usd for i in items), 4)
            t_cny = round(sum(i.cost_saved_cny for i in items), 4)
            cache_hits = sum(1 for i in items if i.cache_hit)
            cache_rate = round((cache_hits / max(1, t_calls)) * 100.0, 2)

            breakdown.append(
                ToolSavingsSummary(
                    tool_name=tool,
                    total_calls=t_calls,
                    total_original_tokens=t_orig,
                    total_optimized_tokens=t_opt,
                    total_saved_tokens=t_saved,
                    average_savings_rate_pct=t_rate,
                    total_cost_saved_usd=t_usd,
                    total_cost_saved_cny=t_cny,
                    cache_hit_rate_pct=cache_rate,
                )
            )

        # Sort breakdown by total_saved_tokens descending
        breakdown.sort(key=lambda x: x.total_saved_tokens, reverse=True)

        headline = (
            f"🎉 本次会话通过智能上下文拦截为您节省了 {total_saved:,} Tokens，"
            f"整体节省率 {overall_rate}%，折合节省约 ¥{total_cny:.2f} / ${total_usd:.2f}"
        )

        return SessionSavingsAudit(
            session_id=session_id,
            total_tool_calls=total_calls,
            total_original_tokens=total_orig,
            total_optimized_tokens=total_opt,
            total_saved_tokens=total_saved,
            overall_savings_rate_pct=overall_rate,
            total_cost_saved_usd=total_usd,
            total_cost_saved_cny=total_cny,
            tool_breakdown=breakdown,
            summary_headline=headline,
        )

    def list_all_sessions(self) -> List[str]:
        with self._lock:
            return list(self._records.keys())
