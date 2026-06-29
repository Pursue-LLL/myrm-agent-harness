"""Agent middleware system.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- context_pipeline_middleware::create_context_pipeline_middleware (POS: 1.)
  (POS: 上下文管道中间件工厂，集成 ContextPipeline)
- debug_logger_middleware::debug_logger_middleware (POS: Provides debug_logger_middleware.)
  (POS: 调试日志中间件，记录完整消息列表)
- filesystem_search_middleware::FilesystemFileSearchMiddleware, (POS: Provides FilesystemFileSearchMiddleware, create_filesystem_search_middleware.)
  (POS: 文件系统搜索中间件，注入 glob/grep 工具)
- tool_interceptor_middleware::tool_interceptor_middleware (POS: Single interception point for all tool calls. Each guard is an independent module; this middleware only orchestrates their execution order.)
  (POS: 工具拦截中间件，异常捕获和验证)
- approval::ApprovalRateLimiter, (POS: Approval queue helpers. Handles AnyMemory ↔ PendingRecord conversion for the approval pipeline. Internal only — not part of the public API.)
  (POS: 审批子系统，含速率限制器)
- concurrency_limiter::create_concurrency_limiter, (POS: Subagent  Semaphore  SUBAGENT_CONFIGS)
  (POS: Subagent 并发限制器，根据 agent_type 限制并发)
- safety_dispatcher::create_safety_dispatcher (POS: TOOL_SAFETY_METADATA  ToolNode  Lock)
  (POS: 工具并发安全分层调度，safe→并发/unsafe→Lock 串行)
- subagent_limit_middleware::subagent_limit_middleware (POS: Subagent limit middleware. Ensures the LLM cannot spawn more than MAX_CONCURRENT_SUBAGENTS in a single turn.)
  (POS: LLM Fan-out 保护，限制单轮 delegate_task 调用数)
- security.tool_result_validator::ValidationResult, (POS: Provides ValidationResult, validate_tool_result, should_apply_validation.)
  (POS: 工具结果验证器，实现位于 security/)

[OUTPUT]
- create_context_pipeline_middleware(): 上下文管道中间件工厂函数
- debug_logger_middleware: 调试日志中间件
- tool_interceptor_middleware: 工具拦截中间件
- FilesystemFileSearchMiddleware: 文件系统搜索中间件类
- create_filesystem_search_middleware(): 文件系统搜索中间件工厂函数
- create_concurrency_limiter(): Subagent 并发限制中间件工厂函数
- create_safety_dispatcher(): 工具并发安全分层调度中间件工厂函数
- get_subagent_semaphore(): 获取特定 agent_type 的 semaphore
- ValidationResult: 验证结果数据类（security 模块的再导出）
- validate_tool_result(): 工具结果验证函数（security 模块的再导出）

[POS]
Agent middleware system exports. Provides the complete middleware stack (context management, debug logging, tool interception, filesystem search).

"""

from myrm_agent_harness.agent.middlewares.approval import (
    ApprovalRateLimiter,
    get_approval_rate_limiter,
)
from myrm_agent_harness.agent.middlewares.auto_session_recall_middleware import (
    auto_session_recall_middleware,
)
from myrm_agent_harness.agent.middlewares.completion_guard import (
    CompletionGuard,
    reset_completion_guard,
)
from myrm_agent_harness.agent.middlewares.concurrency_limiter import (
    create_concurrency_limiter,
    get_subagent_semaphore,
)
from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
    create_context_pipeline_middleware,
)
from myrm_agent_harness.agent.middlewares.debug_logger_middleware import (
    debug_logger_middleware,
)
from myrm_agent_harness.agent.middlewares.filesystem_search_middleware import (
    FilesystemFileSearchMiddleware,
    create_filesystem_search_middleware,
)
from myrm_agent_harness.agent.middlewares.guardrails import (
    GuardrailMiddleware,
    SkillBoundaryProvider,
)
from myrm_agent_harness.agent.middlewares.planner_middleware import planner_middleware
from myrm_agent_harness.agent.middlewares.rate_limit import RateLimitMiddleware
from myrm_agent_harness.agent.middlewares.safety_dispatcher import (
    create_safety_dispatcher,
)
from myrm_agent_harness.agent.middlewares.subagent_limit_middleware import (
    subagent_limit_middleware,
)
from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
    reset_loop_guard,
    tool_interceptor_middleware,
)
from myrm_agent_harness.agent.security.detection.tool_result_validator import (
    ValidationResult,
    validate_tool_result,
)
from myrm_agent_harness.agent.security.guards.frequency_guard import (
    reset_frequency_guard,
)

__all__ = [
    # 速率限制
    "ApprovalRateLimiter",
    # 中间件
    "auto_session_recall_middleware",
    "CompletionGuard",
    "FilesystemFileSearchMiddleware",
    # 权限检查
    "GuardrailMiddleware",
    "RateLimitMiddleware",
    "SkillBoundaryProvider",
    # 验证工具
    "ValidationResult",
    "create_concurrency_limiter",
    "create_context_pipeline_middleware",
    "create_filesystem_search_middleware",
    "create_safety_dispatcher",
    "debug_logger_middleware",
    "get_approval_rate_limiter",
    "get_subagent_semaphore",
    "planner_middleware",
    "reset_completion_guard",
    "reset_frequency_guard",
    "reset_loop_guard",
    "subagent_limit_middleware",
    "tool_interceptor_middleware",
    "validate_tool_result",
]
