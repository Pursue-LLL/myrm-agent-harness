"""Security facade: process-wide Managed Approval Policy for external consumers.

External consumers import here instead of reaching into ``agent.security``.

[INPUT]
- agent.security.managed_approval_policy::ManagedApprovalPolicy / get_process_managed_approval_policy (POS: 进程级托管审批策略)

[OUTPUT]
- myrm_agent_harness.api.security → server 只读 MAP 查询接口
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.managed_approval_policy import (
    ManagedApprovalPolicy,
    configure_process_managed_approval_policy,
    get_process_managed_approval_policy,
    get_process_managed_approval_revision,
    load_managed_approval_policy_from_env,
)
from myrm_agent_harness.utils.url_utils import (
    clear_dynamic_blocked_hostnames,
    register_blocked_hostnames,
    unregister_blocked_hostnames,
)

__all__ = [
    "ManagedApprovalPolicy",
    "clear_dynamic_blocked_hostnames",
    "configure_process_managed_approval_policy",
    "get_process_managed_approval_policy",
    "get_process_managed_approval_revision",
    "load_managed_approval_policy_from_env",
    "register_blocked_hostnames",
    "unregister_blocked_hostnames",
]
