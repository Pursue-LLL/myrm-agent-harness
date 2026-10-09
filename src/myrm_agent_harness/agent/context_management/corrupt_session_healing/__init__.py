"""Corrupt session degradation and auto-healing package.

[INPUT]
- healing_types: contracts and data models.
- corrupt_record_sandbox: CorruptRecordSandbox.
- partial_transcript_salvager: PartialTranscriptSalvager.
- fresh_session_auto_healer: FreshSessionAutoHealer.
- corrupt_session_healing_suite: CorruptSessionStorageGracefulDegradationAndAutoHealingSuite.

[OUTPUT]
- Exposes all core contracts and master facade for corrupt session handling.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.corrupt_session_healing
- Module: __init__.py
"""

from myrm_agent_harness.agent.context_management.corrupt_session_healing.corrupt_record_sandbox import (
    CorruptRecordSandbox,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.corrupt_session_healing_suite import (
    CorruptSessionStorageGracefulDegradationAndAutoHealingSuite,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.fresh_session_auto_healer import (
    FreshSessionAutoHealer,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.healing_types import (
    CorruptRecordArchive,
    HealingSuiteConfig,
    RestorationOutcome,
    RestorationStatus,
    SalvagedMessageItem,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.partial_transcript_salvager import (
    PartialTranscriptSalvager,
)

__all__ = [
    "CorruptRecordArchive",
    "CorruptRecordSandbox",
    "CorruptSessionStorageGracefulDegradationAndAutoHealingSuite",
    "FreshSessionAutoHealer",
    "HealingSuiteConfig",
    "PartialTranscriptSalvager",
    "RestorationOutcome",
    "RestorationStatus",
    "SalvagedMessageItem",
]
