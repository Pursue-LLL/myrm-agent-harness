"""Types and contracts for External CLI Subagent Adapter Bridge and Subscription Passthrough.

[INPUT]
- dataclasses
- enum
- typing

[OUTPUT]
- CliSubagentType
- SubscriptionStatus
- SensitivityLevel
- CliProfileBundle
- DelegationPrivacyDisclosure
- CliTaskDelegationRequest
- CliExecutionResult

[POS]
Types and contracts for External CLI Subagent Adapter Bridge and Subscription Passthrough.

"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CliSubagentType(str, Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CURSOR_CLI = "cursor_cli"
    GENERIC_CLI = "generic_cli"


class SubscriptionStatus(str, Enum):
    ACTIVE_PRO = "active_pro"
    ACTIVE_TEAM = "active_team"
    FREE_TIER = "free_tier"
    UNAUTHENTICATED = "unauthenticated"
    DETECTED = "detected"


class SensitivityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CliProfileBundle:
    bundle_id: str
    cli_type: CliSubagentType
    display_name: str
    executable_name: str
    subscription_status: SubscriptionStatus
    account_email_masked: Optional[str] = None
    default_flags: List[str] = field(default_factory=list)
    timeout_seconds: int = 300
    allowed_workspace_root: str = "/workspace"
    is_installed: bool = True


@dataclass
class DelegationPrivacyDisclosure:
    disclosure_id: str
    cli_type: CliSubagentType
    vendor_name: str
    data_handling_terms_url: str
    context_summary: str
    sensitivity_level: SensitivityLevel
    user_acknowledged: bool = False
    created_at_utc: str = ""


@dataclass
class CliTaskDelegationRequest:
    task_id: str
    bundle_id: str
    instruction: str
    workspace_path: str
    disclosure: DelegationPrivacyDisclosure
    context_files: List[str] = field(default_factory=list)
    dry_run: bool = False


@dataclass
class CliExecutionResult:
    task_id: str
    bundle_id: str
    exit_code: int
    diff_output: str
    structured_summary: str
    tokens_saved_estimate: int
    tamper_proof_audit_hash: str
    egress_accounting_id: str
    completed_at_utc: str
    file_changes_count: int = 0
