"""
[INPUT]: Raw runtime logs, environment vitals, API call traces, and user error reports.
[OUTPUT]: Immutable sanitized debug dump structures, redaction audits, and ephemeral share tokens.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/sanitized_debug_dump/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RedactionRuleType(str, Enum):
    API_KEY = "API_KEY"
    BEARER_TOKEN = "BEARER_TOKEN"
    FILE_SYSTEM_PATH = "FILE_SYSTEM_PATH"
    EMAIL_ADDRESS = "EMAIL_ADDRESS"
    IP_ADDRESS = "IP_ADDRESS"
    PASSWORD_OR_SECRET = "PASSWORD_OR_SECRET"


@dataclass(frozen=True)
class RedactionAuditRecord:
    rule_type: RedactionRuleType
    masked_placeholder: str
    occurrences_count: int


@dataclass
class SystemVitalsSnapshot:
    os_name: str
    python_version: str
    cpu_cores: int
    memory_total_gb: float
    network_connectivity: str
    timestamp: str


@dataclass
class SanitizedDebugDump:
    dump_id: str
    vitals: SystemVitalsSnapshot
    sanitized_logs: List[str]
    recent_traces: List[Dict[str, str]]
    redacted_audits: List[RedactionAuditRecord]
    total_redacted_count: int
    user_note: str = ""
    checksum_sha256: str = ""
    created_at: str = ""


@dataclass
class EphemeralShareLink:
    share_token: str
    dump_id: str
    share_url: str
    expires_at: str
    max_views: int = 3
    remaining_views: int = 3
    is_destroyed: bool = False
    created_at: str = ""
