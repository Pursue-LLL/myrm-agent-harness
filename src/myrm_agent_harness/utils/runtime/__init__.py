"""Agent runtime control primitives — cancellation tokens, progress push, steering injection.

[POS]
Agent run() lifecycle control parameters. All based on ContextVar for request-level isolation.

"""

from importlib import import_module as _import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    # cancellation.py
    "CancellationToken": (".cancellation", "CancellationToken"),
    "CancellationMonitor": (".cancellation", "CancellationMonitor"),
    "CancellationMetrics": (".cancellation_metrics", "CancellationMetrics"),
    "get_cancel_token": (".cancellation", "get_cancel_token"),
    "set_cancel_token": (".cancellation", "set_cancel_token"),
    "create_cancellation_context": (".cancellation", "create_cancellation_context"),
    # progress_sink.py
    "ToolProgressSink": (".progress_sink", "ToolProgressSink"),
    "get_tool_progress_sink": (".progress_sink", "get_tool_progress_sink"),
    "set_tool_progress_sink": (".progress_sink", "set_tool_progress_sink"),
    "create_queue_sink": (".progress_sink", "create_queue_sink"),
    # steering.py
    "SteeringToken": (".steering", "SteeringToken"),
    "STEERING_SKIP_MESSAGE": (".steering", "STEERING_SKIP_MESSAGE"),
    "get_steering_token": (".steering", "get_steering_token"),
    "set_steering_token": (".steering", "set_steering_token"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> object:
    try:
        module_path, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = _import_module(module_path, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__ + [name for name in globals() if not name.startswith("_")]))
