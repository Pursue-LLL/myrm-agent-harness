"""Security facade: process-wide Managed Approval Policy for external consumers.

External consumers import here instead of reaching into ``agent.security``.

[INPUT]
- agent.security.managed_approval_policy::ManagedApprovalPolicy / get_process_managed_approval_policy (POS: 进程级托管审批策略)

[OUTPUT]
- myrm_agent_harness.api.security → server 只读 MAP 查询接口
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.batch_risk import (
    BatchApprovalItem,
    BatchItemRiskLevel,
    BatchRiskItemDetail,
    BatchRiskReport,
    classify_batch_approval_risk,
)
from myrm_agent_harness.agent.security.detection.content_boundary import (
    detect_suspicious,
    wrap_untrusted,
)
from myrm_agent_harness.agent.security.guards import (
    TaintLabel,
    get_taint_tracker,
    set_untrusted_ingress,
)
from myrm_agent_harness.agent.security.managed_approval_policy import (
    ManagedApprovalPolicy,
    configure_process_managed_approval_policy,
    get_process_managed_approval_policy,
    get_process_managed_approval_revision,
    load_managed_approval_policy_from_env,
)
from myrm_agent_harness.core.security.egress.spend_governor import (
    SpendGovernor,
    SpendGovernorConfig,
)
from myrm_agent_harness.toolkits.code_execution.security.task_airbag import (
    TaskAirbagDiffSummary,
    TaskAirbagManifest,
    TaskAirbagStatus,
    arm_task_airbag,
    get_task_airbag_diff,
    rollback_task_airbag,
)
from myrm_agent_harness.toolkits.code_execution.security.workspace_snapshot import (
    WorkspaceSnapshotResult,
    create_workspace_snapshot,
    rollback_workspace_snapshot,
)
from myrm_agent_harness.toolkits.computer_use.screen_detector import (
    ScreenDetector,
    get_default_screen_detector,
)
from myrm_agent_harness.toolkits.computer_use.types import ScreenLockState
from myrm_agent_harness.toolkits.ssh_remote import ReadOnlySSHValidator
from myrm_agent_harness.utils.url_utils import (
    clear_dynamic_blocked_hostnames,
    register_blocked_hostnames,
    unregister_blocked_hostnames,
)

__all__ = [
    "BatchApprovalItem",
    "BatchItemRiskLevel",
    "BatchRiskItemDetail",
    "BatchRiskReport",
    "ManagedApprovalPolicy",
    "ReadOnlySSHValidator",
    "ScreenDetector",
    "ScreenLockState",
    "SpendGovernor",
    "SpendGovernorConfig",
    "TaintLabel",
    "TaskAirbagDiffSummary",
    "TaskAirbagManifest",
    "TaskAirbagStatus",
    "WorkspaceSnapshotResult",
    "arm_task_airbag",
    "classify_batch_approval_risk",
    "clear_dynamic_blocked_hostnames",
    "configure_process_managed_approval_policy",
    "create_workspace_snapshot",
    "detect_suspicious",
    "get_default_screen_detector",
    "get_process_managed_approval_policy",
    "get_process_managed_approval_revision",
    "get_taint_tracker",
    "get_task_airbag_diff",
    "load_managed_approval_policy_from_env",
    "register_blocked_hostnames",
    "rollback_task_airbag",
    "rollback_workspace_snapshot",
    "set_untrusted_ingress",
    "unregister_blocked_hostnames",
    "wrap_untrusted",
]
