"""Command quiet rewriter and subagent log sink package.

[INPUT]
-
  agent.context_management.command_quiet_rewriter.command_quiet_rewriter_suite::CommandQuietRewriterAndLogSinkSuite
  (POS: Command Quiet Rewriter and Subagent Log Sink Suite.)
- agent.context_management.command_quiet_rewriter.preflight_command_rewriter::PreflightCommandRewriter (POS:
  Preflight Command Rewriter that intercepts CLI commands before sandbox execution.)
- agent.context_management.command_quiet_rewriter.quiet_rewriter_types::LogSinkConclusionCard, LogSinkStatus,
  LogSinkTaskSpec, LogSinkTaskType, QuietRewriteRule, RewriteResult, RewriteStatus,
  SubagentLogSinkExecutionRecord (POS: Data contracts and type definitions for preflight command rewriting and
  subagent log sink.)
- agent.context_management.command_quiet_rewriter.subagent_log_sink_engine::SubagentLogSinkEngine (POS:
  Subagent Log Sink Engine that absorbs massive process outputs into isolated contexts.)

[OUTPUT]
- Re-exports: CommandQuietRewriterAndLogSinkSuite, LogSinkConclusionCard, LogSinkStatus, LogSinkTaskSpec,
  LogSinkTaskType, PreflightCommandRewriter, QuietRewriteRule, RewriteResult, RewriteStatus,
  SubagentLogSinkEngine, SubagentLogSinkExecutionRecord

[POS]
Command quiet rewriter and subagent log sink package.
"""

from .command_quiet_rewriter_suite import CommandQuietRewriterAndLogSinkSuite
from .preflight_command_rewriter import PreflightCommandRewriter
from .quiet_rewriter_types import (
    LogSinkConclusionCard,
    LogSinkStatus,
    LogSinkTaskSpec,
    LogSinkTaskType,
    QuietRewriteRule,
    RewriteResult,
    RewriteStatus,
    SubagentLogSinkExecutionRecord,
)
from .subagent_log_sink_engine import SubagentLogSinkEngine

__all__ = [
    "CommandQuietRewriterAndLogSinkSuite",
    "LogSinkConclusionCard",
    "LogSinkStatus",
    "LogSinkTaskSpec",
    "LogSinkTaskType",
    "PreflightCommandRewriter",
    "QuietRewriteRule",
    "RewriteResult",
    "RewriteStatus",
    "SubagentLogSinkEngine",
    "SubagentLogSinkExecutionRecord",
]
