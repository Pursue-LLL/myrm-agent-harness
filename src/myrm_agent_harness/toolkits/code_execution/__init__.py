"""Code execution module for Agent-in-Sandbox architecture.

Provides code execution capabilities within the current container environment.

Core components:
- ExecutionMode, ExecutionConfig: execution configuration
- CodeExecutor, LocalExecutor: code execution engines
- ExecutionContext, ExecutionResult: execution I/O models
- ExecutionMetrics: cumulative execution statistics
- Workspace, WorkspaceService: session workspace management
- create_workspace_service(): workspace service factory (**required** aggregate ``root_dir``)


[INPUT]
- code_execution.config (POS: code execution configuration layer)
- code_execution.executors (POS: code executor implementations)
- code_execution.factory::create_executor (POS: code executor factory)
- code_execution.workspace (POS: session workspace management)

[OUTPUT]
- ExecutionConfig, ExecutionMode, LocalExecutionConfig, MCPIPCConfig, get_execution_config: config types
- CodeExecutor, CodeExecutorMiddleware, LocalExecutor: executor classes
- ExecutionContext, ExecutionResult, ExecutionMetrics: execution I/O models
- MCPCommunicationConfig, MCPConfigItem: MCP communication types
- classify_execution_error, get_executor, require_executor, set_executor: executor utilities
- create_executor: executor factory function
- Workspace, WorkspaceService, WorkspaceStatus, create_workspace_service: workspace management

[POS]
Code execution toolkit entry point. Aggregates execution configuration, executor implementations,
workspace management, and factory functions for the Agent-in-Sandbox architecture.
"""

from myrm_agent_harness.toolkits.code_execution.config import (
    ExecutionConfig,
    ExecutionMode,
    LocalExecutionConfig,
    MCPIPCConfig,
    get_execution_config,
)
from myrm_agent_harness.toolkits.code_execution.executors import (
    CodeExecutor,
    CodeExecutorMiddleware,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    LocalExecutor,
    MCPCommunicationConfig,
    MCPConfigItem,
    classify_execution_error,
    get_executor,
    require_executor,
    set_executor,
)
from myrm_agent_harness.toolkits.code_execution.factory import create_executor
from myrm_agent_harness.toolkits.code_execution.git_digest import (
    RepoCommitItem,
    RepoHistoryEvidenceDigest,
    RepoSyncDecision,
    evaluate_repo_sync_policy,
    extract_repo_history_digest,
)
from myrm_agent_harness.toolkits.code_execution.sandbox_snapshot import (
    SandboxBootstrapSnapshot,
    format_bootstrap_snapshot_xml,
    generate_sandbox_bootstrap_snapshot,
)
from myrm_agent_harness.toolkits.code_execution.workspace import (
    Workspace,
    WorkspaceService,
    WorkspaceStatus,
    create_workspace_service,
)

__all__ = [
    # Executors
    "CodeExecutor",
    "CodeExecutorMiddleware",
    "ExecutionConfig",
    "ExecutionContext",
    "ExecutionMetrics",
    # Configuration
    "ExecutionMode",
    "ExecutionResult",
    "LocalExecutionConfig",
    "LocalExecutor",
    "MCPCommunicationConfig",
    "MCPConfigItem",
    "MCPIPCConfig",
    # Workspace
    "Workspace",
    "WorkspaceService",
    "WorkspaceStatus",
    "classify_execution_error",
    # Factory
    "create_executor",
    "create_workspace_service",
    "get_execution_config",
    # Git Digest & Adaptive Sync
    "RepoCommitItem",
    "RepoHistoryEvidenceDigest",
    "RepoSyncDecision",
    "extract_repo_history_digest",
    "evaluate_repo_sync_policy",
    # Executor ContextVar management
    "get_executor",
    "require_executor",
    "set_executor",
    # Sandbox Bootstrap Snapshot
    "SandboxBootstrapSnapshot",
    "generate_sandbox_bootstrap_snapshot",
    "format_bootstrap_snapshot_xml",
]
