"""Graceful fallback firewall coordinator for resilient agent tool calling.

Orchestrates tool-level circuit breakers, synthesizes safe semantic fallbacks,
and produces real-time reliability telemetry cards.

[INPUT]
- __future__
- json
- collections
- circuit_breaker_types
- tool_circuit_breaker

[OUTPUT]
- ToolCallable
- FallbackCallable
- GracefulFallbackFirewall

[POS]
Graceful fallback firewall coordinator for resilient agent tool calling.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine

from .circuit_breaker_types import (
    CircuitBreakerConfig,
    CircuitState,
    ToolExecutionOutcome,
)
from .tool_circuit_breaker import ToolCircuitBreaker

ToolCallable = Callable[..., Coroutine[object, object, str] | str]
FallbackCallable = Callable[[], str]


class GracefulFallbackFirewall:
    """Central registry and firewall preventing cascading failures through tool circuit breakers."""

    def __init__(self, default_config: CircuitBreakerConfig | None = None) -> None:
        self.default_config = default_config or CircuitBreakerConfig()
        self._breakers: dict[str, ToolCircuitBreaker] = {}

    def get_or_create_breaker(
        self,
        tool_name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> ToolCircuitBreaker:
        """Retrieve existing breaker for tool or initialize a new one with given configuration."""
        if tool_name not in self._breakers:
            cfg = config or self.default_config
            self._breakers[tool_name] = ToolCircuitBreaker(tool_name=tool_name, config=cfg)
        return self._breakers[tool_name]

    async def execute_tool(
        self,
        tool_name: str,
        func: ToolCallable,
        custom_fallback: FallbackCallable | None = None,
        *args: object,
        **kwargs: object,
    ) -> ToolExecutionOutcome:
        """Execute a tool through its circuit breaker with automatic graceful semantic fallback."""
        breaker = self.get_or_create_breaker(tool_name)

        def default_fallback() -> str:
            return self.synthesize_fallback_advice(tool_name)

        fallback_handler = custom_fallback or default_fallback
        return await breaker.execute_with_resilience(
            func,
            fallback_handler,
            *args,
            **kwargs,
        )

    @staticmethod
    def synthesize_fallback_advice(
        tool_name: str,
        guidance: str = "当前服务受限，请基于已有本地记忆与自身推理给出答复，并明确告知用户此项情况。",
    ) -> str:
        """Generate structured JSON fallback guidance safe for LLM context injection."""
        payload: dict[str, str | bool] = {
            "status": "TOOL_CIRCUIT_OPEN",
            "tool_name": tool_name,
            "is_fallback": True,
            "fallback_advice": guidance,
        }
        return json.dumps(payload, ensure_ascii=False)

    def render_firewall_markdown(self) -> str:
        """Render a GitHub Flavored Markdown dashboard of all registered tool circuit breakers."""
        lines: list[str] = [
            "### 🛡️ 工具级自适应熔断器与优雅降级防火墙看板",
            f"- **已纳管工具总数**: `{len(self._breakers)}`",
            "",
            "#### 📊 工具熔断状态矩阵",
        ]

        open_circuits: list[str] = []
        half_open_circuits: list[str] = []

        if self._breakers:
            for name, breaker in self._breakers.items():
                snap = breaker.get_snapshot()
                status_icon = (
                    "🟢" if snap.state == CircuitState.CLOSED
                    else ("🔴" if snap.state == CircuitState.OPEN else "🟡")
                )
                lines.append(
                    f"- {status_icon} **`{name}`** [{snap.state.value}]: 连续失败 `{snap.consecutive_failures}` 次 | 累计调用 `{snap.total_calls}` | 降级触发 `{snap.total_fallbacks}`"
                )
                if snap.state == CircuitState.OPEN:
                    open_circuits.append(name)
                elif snap.state == CircuitState.HALF_OPEN:
                    half_open_circuits.append(name)
        else:
            lines.append("- *(暂无登记工具)*")

        lines.append("")
        if open_circuits:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> **[熔断报警]** 工具 `{', '.join(open_circuits)}` 处于 OPEN 熔断状态。已激活快速失败与语义降级防火墙，杜绝了重试风暴击垮下游。",
                ]
            )
        elif half_open_circuits:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> 工具 `{', '.join(half_open_circuits)}` 处于 HALF_OPEN 恢复探测期，正通过受控单次探测评估服务健康度。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!TIP]",
                    "> 所有纳管工具均处于 CLOSED 正常状态，全抖动退避与熔断防风暴引擎就绪。",
                ]
            )

        return "\n".join(lines)
