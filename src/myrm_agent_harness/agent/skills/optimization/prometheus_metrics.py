"""Prometheus Metrics for Skill Optimization

P2-10: 多维度Prometheus指标，支持按skill_id和version标签聚合。

- Prometheus Counter是只增不减的，不支持删除labels
- 内存管理应在Prometheus server端配置（retention policy + series limit）
- 建议配置：
  * retention: 15d (保留15天数据)
  * max_series: 100000 (限制最大series数量)
  * 启用label值限制（如：skill_id数量<1000）

如需客户端label控制，建议：
1. 使用label值白名单（如：仅允许active skills）
2. 定期重启应用（释放内存）
3. 使用Prometheus Pushgateway（短生命周期metrics）

[INPUT]
- (none)

[OUTPUT]
- record_optimization_start: function — record_optimization_start
- record_optimization_success: function — record_optimization_success
- record_optimization_failure: function — record_optimization_failure
- update_queue_size: function — update_queue_size
- update_circuit_breaker_count: function — update_circuit_breaker_count

[POS]
Prometheus Metrics for Skill Optimization
"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import create_counter, create_gauge, create_histogram

# ==================== P2-10: Prometheus指标定义 ====================

# Counter: 优化任务总数（带标签）
optimization_total = create_counter(
    "skill_optimization_total",
    "Total number of skill optimizations triggered",
    labelnames=("skill_id", "status"),  # status: success/failed/queued
)

# Counter: 优化成功次数
optimization_success = create_counter(
    "skill_optimization_success_total",
    "Total number of successful skill optimizations",
    labelnames=("skill_id", "version"),
)

# Counter: 优化失败次数
optimization_failed = create_counter(
    "skill_optimization_failed_total",
    "Total number of failed skill optimizations",
    labelnames=("skill_id", "reason"),  # reason: circuit_breaker/execution_error/etc
)

# Histogram: 优化耗时
optimization_duration_seconds = create_histogram(
    "skill_optimization_duration_seconds",
    "Time taken to complete skill optimization",
    labelnames=("skill_id", "status"),
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),  # 1s~10min
)

# Gauge: 当前队列大小
optimization_queue_size = create_gauge(
    "skill_optimization_queue_size", "Current number of pending optimizations in queue"
)

# Gauge: 当前断路器触发数
circuit_breaker_tripped = create_gauge(
    "skill_optimization_circuit_breaker_tripped", "Number of skills with circuit breaker tripped"
)

# Gauge: 死信队列大小
dlq_size = create_gauge("skill_optimization_dlq_size", "Number of tasks in dead letter queue")

# Counter: LLM成本统计
llm_cost_usd = create_counter(
    "skill_optimization_llm_cost_usd_total",
    "Total LLM cost in USD for skill optimizations",
    labelnames=("skill_id", "model"),
)

# Counter: LLM Token统计
llm_tokens = create_counter(
    "skill_optimization_llm_tokens_total",
    "Total LLM tokens consumed for skill optimizations",
    labelnames=("skill_id", "model", "token_type"),  # token_type: prompt/completion
)


# ==================== 辅助函数 ====================


def record_optimization_start(skill_id: str) -> None:
    """记录优化开始"""
    optimization_total.labels(skill_id=skill_id, status="queued").inc()


def record_optimization_success(skill_id: str, version: int, duration: float) -> None:
    """记录优化成功"""
    optimization_total.labels(skill_id=skill_id, status="success").inc()
    optimization_success.labels(skill_id=skill_id, version=str(version)).inc()
    optimization_duration_seconds.labels(skill_id=skill_id, status="success").observe(duration)


def record_optimization_failure(skill_id: str, reason: str, duration: float) -> None:
    """记录优化失败"""
    optimization_total.labels(skill_id=skill_id, status="failed").inc()
    optimization_failed.labels(skill_id=skill_id, reason=reason).inc()
    optimization_duration_seconds.labels(skill_id=skill_id, status="failed").observe(duration)


def update_queue_size(size: int) -> None:
    """更新队列大小"""
    optimization_queue_size.set(size)


def update_circuit_breaker_count(count: int) -> None:
    """更新断路器触发数"""
    circuit_breaker_tripped.set(count)


def update_dlq_size(size: int) -> None:
    """更新DLQ大小"""
    dlq_size.set(size)


def record_llm_cost(skill_id: str, model: str, cost_usd: float) -> None:
    """记录LLM成本"""
    llm_cost_usd.labels(skill_id=skill_id, model=model).inc(cost_usd)


def record_llm_tokens(skill_id: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """记录LLM Token消耗"""
    llm_tokens.labels(skill_id=skill_id, model=model, token_type="prompt").inc(prompt_tokens)
    llm_tokens.labels(skill_id=skill_id, model=model, token_type="completion").inc(completion_tokens)
