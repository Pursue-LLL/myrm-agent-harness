"""Domain models and contracts for Creator Mode Guardrailed Agent Preset Synthesizer
and Defensive Sandbox (Item 39).

[INPUT]
- Natural language intent, target tools inventory, defensive test case definitions,
  and multi-platform roaming target platforms.

[OUTPUT]
- Strongly-typed models for AgentPresetDraft, DefensiveTestCase, SandboxVerificationReport,
  and RoamingSyncRecord.

[POS]
- Harness creator_mode layer domain contracts.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class CaseVerdict(enum.StrEnum):
    """Execution authorization verdict for sandbox defense tests."""

    ALLOW = "allow"
    BLOCK = "block"


class RoamingPlatform(enum.StrEnum):
    """Deployment targets for multi-platform unified agent profile roaming."""

    WEBUI = "webui"
    DESKTOP_TAURI = "desktop_tauri"
    CLOUD = "cloud"


@dataclass(frozen=True)
class AgentPresetDraft:
    """Synthesized agent profile configuration draft with least-privilege tool boundaries."""

    preset_id: str
    name: str
    role: str
    description: str
    system_prompt: str
    allowed_tools: frozenset[str]
    denied_tools: frozenset[str]
    guardrails: dict[str, bool | int | str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class DefensiveTestCase:
    """Individual positive capability or negative penetration exploit test case."""

    case_id: str
    name: str
    is_exploit: bool
    prompt_input: str
    target_tool: str
    expected_verdict: CaseVerdict


@dataclass(frozen=True)
class CaseEvaluationResult:
    """Evaluation result for an individual defensive or capability test case."""

    case_id: str
    name: str
    is_exploit: bool
    passed: bool
    actual_verdict: CaseVerdict
    reason: str


@dataclass(frozen=True)
class SandboxVerificationReport:
    """Consolidated report from executing the defensive sandbox test battery."""

    is_safe: bool
    total_cases: int
    passed_cases: int
    blocked_exploits: int
    results: list[CaseEvaluationResult] = field(default_factory=list)
    summary: str = ""
    verified_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True)
class RoamingSyncRecord:
    """Sync and self-healing record across target platforms for a preset."""

    preset_id: str
    platform: RoamingPlatform
    target_path: str
    status: str
    healed: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
