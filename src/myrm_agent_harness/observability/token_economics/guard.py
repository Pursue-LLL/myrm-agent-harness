"""
[INPUT]: BudgetGuardPolicy, current cost, token count, duration seconds.
[OUTPUT]: BudgetGuardEvaluation with soft warnings, circuit breaker trip states, and suggested actions.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/token_economics/guard.py
"""

from .models import BudgetGuardEvaluation, BudgetGuardPolicy, GuardStatus


class RunawayCostGuard:
    """
    Enforces real-time budget circuit breakers and runaway cost guards
    to prevent unexpected billing spikes caused by infinite loops or cache busts.
    """

    @staticmethod
    def evaluate(
        policy: BudgetGuardPolicy,
        current_cost_rmb: float,
        current_tokens: int,
        duration_seconds: float,
    ) -> BudgetGuardEvaluation:
        duration_mins = max(0.1 / 60.0, duration_seconds / 60.0)
        burn_rate_rmb_min = round(current_cost_rmb / duration_mins, 4)

        # 1. Hard circuit breaker check
        if current_cost_rmb >= policy.max_allowed_cost_rmb:
            return BudgetGuardEvaluation(
                status=GuardStatus.CIRCUIT_BREAKER_TRIPPED,
                current_cost_rmb=current_cost_rmb,
                current_burn_rate_rmb_min=burn_rate_rmb_min,
                current_tokens=current_tokens,
                is_paused=True,
                reason=f"单任务成本累计达 ¥{current_cost_rmb:.2f}，触发硬预算熔断限额 (上限 ¥{policy.max_allowed_cost_rmb:.2f})。",
                suggested_action="任务已被保护性自动挂起，请审查是否存在多轮重复工具调用，或手动追加预算恢复执行。",
            )

        if current_tokens >= policy.max_allowed_tokens:
            return BudgetGuardEvaluation(
                status=GuardStatus.CIRCUIT_BREAKER_TRIPPED,
                current_cost_rmb=current_cost_rmb,
                current_burn_rate_rmb_min=burn_rate_rmb_min,
                current_tokens=current_tokens,
                is_paused=True,
                reason=f"单任务 Token 消耗达 {current_tokens:,}，突破防刺客熔断警戒线 ({policy.max_allowed_tokens:,})。",
                suggested_action="任务已被保护性自动挂起，建议精简上下文提示词或手动放行。",
            )

        if burn_rate_rmb_min >= policy.max_burn_rate_rmb_per_minute and duration_seconds > 10.0:
            return BudgetGuardEvaluation(
                status=GuardStatus.CIRCUIT_BREAKER_TRIPPED,
                current_cost_rmb=current_cost_rmb,
                current_burn_rate_rmb_min=burn_rate_rmb_min,
                current_tokens=current_tokens,
                is_paused=True,
                reason=f"算力燃速异常激增至 ¥{burn_rate_rmb_min:.2f}/min，超过安全阈值 ¥{policy.max_burn_rate_rmb_per_minute:.2f}/min。",
                suggested_action="疑似发生死循环或高频大文件刷屏，已自动熔断刹车保护。",
            )

        # 2. Soft warning check
        if current_cost_rmb >= policy.soft_warning_threshold_rmb:
            return BudgetGuardEvaluation(
                status=GuardStatus.SOFT_WARNING,
                current_cost_rmb=current_cost_rmb,
                current_burn_rate_rmb_min=burn_rate_rmb_min,
                current_tokens=current_tokens,
                is_paused=False,
                reason=f"当前开销 ¥{current_cost_rmb:.2f} 已达到软预警线 ¥{policy.soft_warning_threshold_rmb:.2f} (70% 水位)。",
                suggested_action="请关注任务进展，必要时可提前结束或调整模型配额。",
            )

        # 3. Healthy state
        return BudgetGuardEvaluation(
            status=GuardStatus.OK,
            current_cost_rmb=current_cost_rmb,
            current_burn_rate_rmb_min=burn_rate_rmb_min,
            current_tokens=current_tokens,
            is_paused=False,
            reason="算力燃烧率与累计开销处于安全正常水位。",
            suggested_action="保持正常执行。",
        )
