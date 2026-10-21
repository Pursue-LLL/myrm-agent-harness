"""Type definitions for Five Vertical Role Persona Presets and Sub-Bot Sandbox Tester (Item 64).

[INPUT]
- Subagent role specifications, unit-test inputs, and A2A communication events.

[OUTPUT]
- VerticalRoleCategory, ReasoningEffort, VerticalRolePreset, SubBotTestRequest, SubBotTestResult, A2AFlowStep, A2AFlowTrace.

[POS]
- Harness orchestration definitions for production vertical agent presets and isolated sub-bot testing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class VerticalRoleCategory(StrEnum):
    """Five core vertical agent persona categories based on production Hermes best practices."""

    LIFE_ADMIN = "life_admin"
    OFFICE_MANAGER = "office_manager"
    CLIPPER = "clipper"
    CHIEF_OF_STAFF = "chief_of_staff"
    SALES_TEAM = "sales_team"


class ReasoningEffort(StrEnum):
    """Dedicated reasoning effort tier for vertical specialists."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class VerticalRolePreset:
    """Out-of-the-box vertical persona preset specification."""

    role_id: str
    category: VerticalRoleCategory
    display_name: str
    description: str
    persona_prompt: str
    recommended_skills: list[str] = field(default_factory=list)
    recommended_tools: list[str] = field(default_factory=list)
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    typical_tasks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SubBotTestRequest:
    """Request payload to test a single specialist bot in an isolated sandbox."""

    role_id: str
    test_prompt: str
    mock_inputs: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class SubBotTestResult:
    """Execution feedback and telemetry from an isolated sub-bot unit test."""

    test_id: str
    role_id: str
    success: bool
    output_text: str
    tool_calls_made: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    logs: list[str] = field(default_factory=list)
    error_message: str | None = None


@dataclass(slots=True)
class A2AFlowStep:
    """A single dispatched interaction in an Agent-to-Agent communication chain."""

    step_id: str
    source_agent_id: str
    target_agent_id: str
    action: str
    payload_summary: str
    result_summary: str = ""
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class A2AFlowTrace:
    """End-to-end trace of A2A communications across a multi-agent task execution."""

    trace_id: str
    session_id: str
    root_agent_id: str
    steps: list[A2AFlowStep] = field(default_factory=list)
    total_duration_ms: float = 0.0
    is_loop_detected: bool = False
