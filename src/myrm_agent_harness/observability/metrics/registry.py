"""Metrics Registry for the Harness Layer.

[INPUT]
- prometheus_client::Counter, Histogram, generate_latest
- myrm_agent_harness.agent.config::AgentConfig (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)

[OUTPUT]
- MetricsRegistry: Singleton registry for agent metrics.
- generate_prometheus_metrics: Returns Prometheus metrics as text.

[POS]
Provides standard, built-in metrics collection for the Agent framework.
Does NOT start an HTTP server, respecting the framework boundary.
Exposes a text generation function for the Server layer to expose.
Includes tool argument recovery metrics for malformed LLM tool-call payloads.
"""

from __future__ import annotations

import logging

try:
    from prometheus_client import Counter, Histogram, generate_latest
    from prometheus_client.core import CollectorRegistry

    PROMETHEUS_AVAILABLE = True
except (ImportError, TypeError):
    PROMETHEUS_AVAILABLE = False
    Counter = None
    Histogram = None
    CollectorRegistry = None
    generate_latest = None

logger = logging.getLogger(__name__)


class MetricsRegistry:
    """Singleton registry for agent metrics."""

    _instance: MetricsRegistry | None = None

    def __new__(cls) -> MetricsRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._initialized = True
        self.enabled = PROMETHEUS_AVAILABLE

        if not self.enabled:
            logger.debug("prometheus_client not installed. Metrics collection disabled.")
            return

        from prometheus_client import REGISTRY

        self.registry = REGISTRY

        # Define standard metrics
        self.agent_execution_duration_seconds = Histogram(
            "agent_execution_duration_seconds",
            "Agent execution duration in seconds",
            ["agent_id", "status"],
            registry=self.registry,
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, float("inf")),
        )

        self.agent_tool_calls_total = Counter(
            "agent_tool_calls_total",
            "Total number of tool calls",
            ["agent_id", "tool_name", "status"],
            registry=self.registry,
        )

        self.agent_tokens_total = Counter(
            "agent_tokens_total",
            "Total LLM tokens consumed",
            ["agent_id", "model", "token_type"],  # token_type: prompt, completion
            registry=self.registry,
        )

        self.agent_tool_arg_recovery_total = Counter(
            "agent_tool_arg_recovery_total",
            "Total number of tool argument recovery attempts",
            ["agent_id", "tool_name", "strategy", "safe"],
            registry=self.registry,
        )

    def record_execution(self, agent_id: str, duration_s: float, status: str = "success") -> None:
        """Record agent execution duration."""
        if self.enabled:
            self.agent_execution_duration_seconds.labels(agent_id=agent_id, status=status).observe(duration_s)

    def record_tool_call(self, agent_id: str, tool_name: str, status: str = "success") -> None:
        """Record a tool call."""
        if self.enabled:
            self.agent_tool_calls_total.labels(agent_id=agent_id, tool_name=tool_name, status=status).inc()

    def record_tokens(self, agent_id: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token consumption."""
        if self.enabled:
            if prompt_tokens > 0:
                self.agent_tokens_total.labels(agent_id=agent_id, model=model, token_type="prompt").inc(prompt_tokens)
            if completion_tokens > 0:
                self.agent_tokens_total.labels(agent_id=agent_id, model=model, token_type="completion").inc(
                    completion_tokens
                )

    def record_tool_arg_recovery(self, agent_id: str, tool_name: str, strategy: str, safe: bool) -> None:
        """Record a tool argument recovery attempt."""
        if self.enabled:
            self.agent_tool_arg_recovery_total.labels(
                agent_id=agent_id,
                tool_name=tool_name,
                strategy=strategy,
                safe=str(safe).lower(),
            ).inc()

    def generate_metrics_text(self) -> str:
        """Generate Prometheus metrics text format."""
        if not self.enabled:
            return "# prometheus_client not installed"
        return generate_latest(self.registry).decode("utf-8")


# Global singleton instance
metrics_registry = MetricsRegistry()


def generate_prometheus_metrics() -> str:
    """Generate Prometheus metrics text format.

    This function is intended to be called by the Server layer
    to expose the metrics via an HTTP endpoint.
    """
    return metrics_registry.generate_metrics_text()
