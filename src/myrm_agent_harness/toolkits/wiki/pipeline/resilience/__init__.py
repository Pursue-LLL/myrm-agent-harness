"""Wiki compile resilience: failure policy, circuit pause, display sanitization.

[INPUT]
- .circuit::CompileCircuitStore (POS: SQLite compile circuit store)
- .failure_policy::evaluate_batch_pause, is_transient_error_kind, resolve_embed_failure, resolve_io_failure, resolve_llm_failure (POS: error resolution rules)
- .sanitize::sanitize_display_message (POS: display message sanitizer)
- .types::CompilePhase, CompileRunSnapshot, FailureResolution (POS: resilience state types)

[OUTPUT]
- CompileCircuitStore, CompilePhase, CompileRunSnapshot, FailureResolution, sanitize_display_message

[POS]
Compile Resilience 编译弹性与熔断模块入口。管理编译失败分类、熔断断路器持久化及用户级脱敏。
"""

from .circuit import CompileCircuitStore
from .failure_policy import (
    EMBED_WINDOW_VIOLATION,
    IO_MISSING,
    evaluate_batch_pause,
    is_transient_error_kind,
    resolve_embed_failure,
    resolve_io_failure,
    resolve_llm_failure,
)
from .sanitize import sanitize_display_message
from .types import CompilePhase, CompileRunSnapshot, FailureResolution

__all__ = [
    "EMBED_WINDOW_VIOLATION",
    "IO_MISSING",
    "CompileCircuitStore",
    "CompilePhase",
    "CompileRunSnapshot",
    "FailureResolution",
    "evaluate_batch_pause",
    "is_transient_error_kind",
    "resolve_embed_failure",
    "resolve_io_failure",
    "resolve_llm_failure",
    "sanitize_display_message",
]
