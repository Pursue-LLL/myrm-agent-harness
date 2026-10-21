"""
[INPUT]: Session savings audits, raw tool execution traces, retry events, and role filter flags.
[OUTPUT]: 7-dimensional EngineeringSignalItem detections and RoleEngineeringInsightReport actionable summaries.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/context_optimization/signal_analyzer.py
"""

from typing import Dict, List, Optional

from .models import (
    EngineeringSignalItem,
    EngineeringSignalPattern,
    RoleEngineeringInsightReport,
    RoleInsightView,
    SessionSavingsAudit,
    ToolSavingsRecord,
)


class EngineeringSignalAnalyzer:
    """
    Analyzes agentic execution sessions across 7 critical engineering dimensions,
    pinpointing tool-level retry bottlenecks, output bloat, blocking I/O, and cache starvation.
    """

    def __init__(
        self,
        bloat_token_threshold: int = 15_000,
        high_retry_threshold: int = 3,
        blocking_io_ms_threshold: float = 5_000.0,
    ) -> None:
        self._bloat_threshold = bloat_token_threshold
        self._retry_threshold = high_retry_threshold
        self._blocking_threshold = blocking_io_ms_threshold

    def analyze_session_signals(
        self,
        audit: SessionSavingsAudit,
        tool_records: List[ToolSavingsRecord],
        tool_retry_counts: Optional[Dict[str, int]] = None,
        tool_latencies_ms: Optional[Dict[str, float]] = None,
    ) -> List[EngineeringSignalItem]:
        signals: List[EngineeringSignalItem] = []
        retries = tool_retry_counts or {}
        latencies = tool_latencies_ms or {}

        # 1. Detect TOOL_OUTPUT_BLOAT (原始输出巨大，依赖截断)
        for summary in audit.tool_breakdown:
            if summary.total_original_tokens > self._bloat_threshold:
                signals.append(
                    EngineeringSignalItem(
                        signal_pattern=EngineeringSignalPattern.TOOL_OUTPUT_BLOAT,
                        severity="HIGH" if summary.total_original_tokens > 50_000 else "MEDIUM",
                        target_entity=summary.tool_name,
                        detected_metric_value=float(summary.total_original_tokens),
                        metric_threshold=float(self._bloat_threshold),
                        root_cause_explanation=(
                            f"工具 '{summary.tool_name}' 原始产出 {summary.total_original_tokens:,} tokens，"
                            f"存在剧烈输出膨胀，高度依赖智能体上下文拦截。"
                        ),
                        actionable_remediation="建议配置按需分页或在工具入参层主动约束输出行数限制。",
                    )
                )

        # 2. Detect HIGH_RETRY_CHURN (重试死循环消耗)
        for tool_name, retry_count in retries.items():
            if retry_count >= self._retry_threshold:
                signals.append(
                    EngineeringSignalItem(
                        signal_pattern=EngineeringSignalPattern.HIGH_RETRY_CHURN,
                        severity="HIGH",
                        target_entity=tool_name,
                        detected_metric_value=float(retry_count),
                        metric_threshold=float(self._retry_threshold),
                        root_cause_explanation=(
                            f"工具 '{tool_name}' 遭遇连续重试 {retry_count} 次，"
                            "产生大量无效 Token 与时间浪费。"
                        ),
                        actionable_remediation="检查工具鉴权有效性或在第 2 次失败后主动介入自诊降级。",
                    )
                )

        # 3. Detect LONG_BLOCKING_IO (长耗时阻塞网络/磁盘)
        for tool_name, duration_ms in latencies.items():
            if duration_ms >= self._blocking_threshold:
                signals.append(
                    EngineeringSignalItem(
                        signal_pattern=EngineeringSignalPattern.LONG_BLOCKING_IO,
                        severity="MEDIUM",
                        target_entity=tool_name,
                        detected_metric_value=duration_ms,
                        metric_threshold=self._blocking_threshold,
                        root_cause_explanation=(
                            f"工具 '{tool_name}' 阻塞耗时 {duration_ms:.0f}ms，"
                            "可能存在慢请求网络瓶颈或低效沙箱执行。"
                        ),
                        actionable_remediation="建议在客户端启用并发异步拉取或增加短超时断路器。",
                    )
                )

        # 4. Detect CACHE_STARVATION (全会话缓存命中饥渴)
        if audit.total_tool_calls >= 3:
            total_cache_hits = sum(1 for r in tool_records if r.cache_hit)
            cache_hit_rate = round((total_cache_hits / max(1, audit.total_tool_calls)) * 100.0, 2)
            if cache_hit_rate < 20.0:
                signals.append(
                    EngineeringSignalItem(
                        signal_pattern=EngineeringSignalPattern.CACHE_STARVATION,
                        severity="LOW",
                        target_entity="prompt_cache",
                        detected_metric_value=cache_hit_rate,
                        metric_threshold=20.0,
                        root_cause_explanation=(
                            f"多轮会话 Prompt Cache 命中率仅为 {cache_hit_rate}%，"
                            "存在前缀频繁抖动或时间戳破坏静态前缀的情况。"
                        ),
                        actionable_remediation="保持静态 Prompt 和系统指令置顶，避免在系统级消息插入动态时间戳。",
                    )
                )

        return signals

    def generate_role_insight(
        self,
        role: RoleInsightView,
        evaluated_sessions: List[SessionSavingsAudit],
        all_signals: List[EngineeringSignalItem],
    ) -> RoleEngineeringInsightReport:
        sessions_count = len(evaluated_sessions)
        total_saved_tokens = sum(s.total_saved_tokens for s in evaluated_sessions)
        total_saved_usd = round(sum(s.total_cost_saved_usd for s in evaluated_sessions), 4)

        # Identify top efficiency tools
        tool_efficiency: Dict[str, int] = {}
        for s in evaluated_sessions:
            for b in s.tool_breakdown:
                tool_efficiency[b.tool_name] = tool_efficiency.get(b.tool_name, 0) + b.total_saved_tokens
        sorted_tools = sorted(tool_efficiency.keys(), key=lambda k: tool_efficiency[k], reverse=True)
        top_tools = sorted_tools[:3]

        # Filter signals based on role focus
        filtered_signals: List[EngineeringSignalItem] = []
        if role == RoleInsightView.CTO:
            # CTO cares about architecture bloat & deadlocks
            filtered_signals = [
                s for s in all_signals
                if s.signal_pattern in (
                    EngineeringSignalPattern.TOOL_OUTPUT_BLOAT,
                    EngineeringSignalPattern.SUBAGENT_DEADLOCK,
                    EngineeringSignalPattern.COST_ANOMALY,
                )
            ]
            headline = f"CTO 视窗: 累计节省 {total_saved_tokens:,} Tokens，重点防范输出膨胀与死锁瓶颈。"

        elif role == RoleInsightView.FINOPS:
            # FinOps cares about cost anomalies, cache hit rates, savings ROI
            filtered_signals = [
                s for s in all_signals
                if s.signal_pattern in (
                    EngineeringSignalPattern.COST_ANOMALY,
                    EngineeringSignalPattern.CACHE_STARVATION,
                    EngineeringSignalPattern.TOOL_OUTPUT_BLOAT,
                )
            ]
            headline = f"FinOps 视窗: 累计为组织挽回 ${total_saved_usd:.2f} 预算，聚焦缓存利用与成本刺客。"

        elif role == RoleInsightView.DEVOPS:
            # DevOps cares about flaky environment, blocking IO, retry churn
            filtered_signals = [
                s for s in all_signals
                if s.signal_pattern in (
                    EngineeringSignalPattern.HIGH_RETRY_CHURN,
                    EngineeringSignalPattern.LONG_BLOCKING_IO,
                    EngineeringSignalPattern.FLAKY_ENVIRONMENT,
                )
            ]
            headline = f"DevOps 视窗: 关注网络阻塞与重试故障，保障 Agent 沙箱环境鲁棒性。"

        else:  # EM
            filtered_signals = all_signals
            headline = f"EM 视窗: 研发效能全景透视，累计优化 {total_saved_tokens:,} Tokens 算力损耗。"

        return RoleEngineeringInsightReport(
            role=role,
            evaluated_sessions_count=sessions_count,
            total_saved_tokens_aggregate=total_saved_tokens,
            total_cost_saved_usd_aggregate=total_saved_usd,
            top_efficiency_tools=top_tools,
            identified_engineering_signals=filtered_signals,
            primary_bottleneck_summary=headline,
        )
