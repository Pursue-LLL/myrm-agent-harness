"""Observability - Metrics and Structured Logging

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]

[OUTPUT]
- MetricsCollector: 指标收集器
- structured_log: 结构化日志函数

[POS]
Lightweight observability support with zero external dependencies. Provides MetricsCollector, Timer, and structured logging.

"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class MetricType(StrEnum):
    """Metric类型"""

    COUNTER = "counter" # 计数器（只增不减）
    GAUGE = "gauge" # 仪表（可增可减）
    HISTOGRAM = "histogram" # 直方图（记录分布）


@dataclass
class MetricValue:
    """Metric值"""

    value: float
    timestamp: datetime
    labels: dict[str, str]


class MetricsCollector:
    """指标收集器

    轻量级metrics收集，支持：
    1. Counter: 优化次数、成功/失败次数
    2. Gauge: 正在运行的优化数、A/B测试数
    3. Histogram: 优化耗时、LLM延迟

    线程安全，可用于并发环境。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Counter metrics {name: {labels_key: value}}
        self._counters: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))

        # Gauge metrics {name: {labels_key: value}}
        self._gauges: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))

        # Histogram metrics {name: {labels_key: [values]}}
        self._histograms: defaultdict[str, defaultdict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

        # Metric metadata {name: (type, description, unit)}
        self._metadata: dict[str, tuple[MetricType, str, str]] = {}

        # 注册内置metrics
        self._register_builtin_metrics()

    def _register_builtin_metrics(self) -> None:
        """注册内置metrics"""
        self.register_metric(
            "skill_optimizations_total", MetricType.COUNTER, "Total number of skill optimizations", "count"
        )
        self.register_metric(
            "skill_optimizations_success_total", MetricType.COUNTER, "Number of successful skill optimizations", "count"
        )
        self.register_metric(
            "skill_optimizations_failed_total", MetricType.COUNTER, "Number of failed skill optimizations", "count"
        )
        self.register_metric(
            "skill_optimizations_duration_seconds", MetricType.HISTOGRAM, "Duration of skill optimizations", "seconds"
        )
        self.register_metric(
            "skill_optimizations_active", MetricType.GAUGE, "Number of active skill optimizations", "count"
        )
        self.register_metric("ab_tests_active", MetricType.GAUGE, "Number of active A/B tests", "count")
        self.register_metric("ab_tests_completed_total", MetricType.COUNTER, "Number of completed A/B tests", "count")
        self.register_metric("llm_calls_total", MetricType.COUNTER, "Total number of LLM calls", "count")
        self.register_metric("llm_calls_duration_seconds", MetricType.HISTOGRAM, "Duration of LLM calls", "seconds")

    def register_metric(self, name: str, metric_type: MetricType, description: str, unit: str = "") -> None:
        """注册metric

        Args:
            name: Metric名称
            metric_type: Metric类型
            description: 描述
            unit: 单位
        """
        self._metadata[name] = (metric_type, description, unit)

    def inc_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """增加counter

        Args:
            name: Counter名称
            value: 增量
            labels: 标签
        """
        labels = labels or {}
        labels_key = self._make_labels_key(labels)

        with self._lock:
            self._counters[name][labels_key] += value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """设置gauge值

        Args:
            name: Gauge名称
            value: 值
            labels: 标签
        """
        labels = labels or {}
        labels_key = self._make_labels_key(labels)

        with self._lock:
            self._gauges[name][labels_key] = value

    def inc_gauge(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """增加gauge值

        Args:
            name: Gauge名称
            value: 增量
            labels: 标签
        """
        labels = labels or {}
        labels_key = self._make_labels_key(labels)

        with self._lock:
            self._gauges[name][labels_key] = self._gauges[name].get(labels_key, 0.0) + value

    def dec_gauge(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """减少gauge值

        Args:
            name: Gauge名称
            value: 减量
            labels: 标签
        """
        self.inc_gauge(name, -value, labels)

    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """记录histogram观测值

        Args:
            name: Histogram名称
            value: 观测值
            labels: 标签
        """
        labels = labels or {}
        labels_key = self._make_labels_key(labels)

        with self._lock:
            self._histograms[name][labels_key].append(value)

    def get_metrics(self) -> dict[str, Any]:
        """获取所有metrics

        Returns:
            dict: {metric_name: {labels_key: value/stats}}
        """
        with self._lock:
            result: dict[str, Any] = {}

            # Counters
            for name, labels_dict in self._counters.items():
                result[name] = dict(labels_dict)

            # Gauges
            for name, labels_dict in self._gauges.items():
                result[name] = dict(labels_dict)

            # Histograms - 计算统计值
            for name, labels_dict in self._histograms.items():
                result[name] = {}
                for labels_key, values in labels_dict.items():
                    if values:
                        result[name][labels_key] = {
                            "count": len(values),
                            "sum": sum(values),
                            "min": min(values),
                            "max": max(values),
                            "avg": sum(values) / len(values),
                        }

            return result

    def reset_metrics(self) -> None:
        """重置所有metrics（主要用于测试）"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()

    def _make_labels_key(self, labels: dict[str, str]) -> str:
        """生成labels的key"""
        if not labels:
            return "__default__"
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


# 全局metrics收集器实例
_global_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """获取全局metrics收集器"""
    return _global_metrics


# ==================== Structured Logging ====================


def structured_log(logger: logging.Logger, level: str, message: str, **kwargs: Any) -> None:
    """结构化日志

    使用标准logging，通过extra参数添加结构化字段。

    Args:
        logger: Logger实例
        level: 日志级别（INFO/WARNING/ERROR）
        message: 日志消息
        **kwargs: 额外字段

    Example:
        structured_log(
            logger,
            "INFO",
            "Skill optimization started",
            skill_id="my-skill",
            skill_type="PREBUILT",
            quality_score=0.65)
    """
    log_fn = getattr(logger, level.lower())

    # 添加timestamp
    kwargs["timestamp"] = datetime.now().isoformat()

    # 使用extra参数添加结构化字段
    log_fn(message, extra={"structured_data": kwargs})


class Timer:
    """Timer上下文管理器

    自动记录代码块执行时间到histogram。

    Example:
        with Timer("llm_calls_duration_seconds", labels={"operation": "optimize"}):
            result = await llm.ainvoke(prompt)
    """

    def __init__(
        self, metric_name: str, labels: dict[str, str] | None = None, collector: MetricsCollector | None = None
    ):
        self.metric_name = metric_name
        self.labels = labels or {}
        self.collector = collector or get_metrics_collector()
        self.start_time: float | None = None

    def __enter__(self) -> "Timer":
        self.start_time = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.collector.observe_histogram(self.metric_name, duration, self.labels)

    async def __aenter__(self) -> "Timer":
        self.start_time = time.time()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.collector.observe_histogram(self.metric_name, duration, self.labels)
