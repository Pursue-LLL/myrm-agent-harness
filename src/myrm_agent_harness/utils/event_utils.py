"""事件工具

提供统一的事件分发机制，兼容 LangGraph 0.1.x 和 0.2.x+ 的 custom stream mode。

[INPUT]
- (none)

[OUTPUT]
- dispatch_custom_event: Args:

[POS]
Provides dispatch_custom_event.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import var_child_runnable_config


def resolve_tool_call_id_from_config(config: RunnableConfig | None) -> str | None:
    """Extract the active tool_call_id from LangGraph/LangChain RunnableConfig."""
    if config is None:
        config = var_child_runnable_config.get()
    if not config:
        return None
    metadata = config.get("metadata")
    if isinstance(metadata, dict):
        for key in ("tool_call_id", "langgraph_tool_call_id"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    configurable = config.get("configurable")
    if isinstance(configurable, dict):
        for key in ("tool_call_id", "langgraph_tool_call_id", "__tool_call_id"):
            value = configurable.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


async def dispatch_custom_event(name: str, data: Any, config: RunnableConfig | None = None) -> None:
    """分发自定义事件，兼容不同版本的 LangGraph。

    在 LangGraph 0.2.x+ 中，stream_mode="custom" 仅捕获通过 StreamWriter 写入的事件。
    此函数优先尝试使用 StreamWriter，如果不可用则回退到 LangChain 的 adispatch_custom_event。

    Args:
        name: 事件名称
        data: 事件数据
        config: RunnableConfig，用于提取 StreamWriter 或传递给 adispatch_custom_event
    """
    if not config:
        config = var_child_runnable_config.get()

    if config:
        # 尝试提取 LangGraph 的 StreamWriter (兼容 LangGraph 0.2.x+)
        runtime = config.get("configurable", {}).get("__pregel_runtime")
        if runtime and hasattr(runtime, "stream_writer"):
            try:
                # StreamWriter 期望接收一个 dict，其中包含 name 和 data
                runtime.stream_writer({"name": name, "data": data})
                return
            except Exception:
                pass

    # 回退到 LangChain 的 adispatch_custom_event (兼容 LangGraph 0.1.x)
    from langchain_core.callbacks.manager import adispatch_custom_event

    await adispatch_custom_event(name, data, config=config)
