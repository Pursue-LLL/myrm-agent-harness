"""[INPUT] None.
[OUTPUT] Public facade exports for Heterogeneous External Agent Bridge & CLI Process Adapter.
[POS] Subagent CLI adapter package root.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.cli_adapter.adapter import (
    ExternalCliAgentAdapter,
)
from myrm_agent_harness.agent.sub_agents.cli_adapter.stream_cleaner import (
    compute_receipt_hash,
    sanitize_cli_output,
)
from myrm_agent_harness.agent.sub_agents.cli_adapter.types import (
    ExternalAgentConfig,
    ExternalAgentKind,
    ProcessExecutionRequest,
    ProcessLaneStatus,
    ProcessReceipt,
)

__all__ = [
    "ExternalAgentConfig",
    "ExternalAgentKind",
    "ExternalCliAgentAdapter",
    "ProcessExecutionRequest",
    "ProcessLaneStatus",
    "ProcessReceipt",
    "compute_receipt_hash",
    "sanitize_cli_output",
]
