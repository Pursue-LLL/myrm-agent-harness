"""[INPUT]
- None (pure domain model definitions)

[OUTPUT]
- SwarmModeConfig, SwarmSubagentTask, RecalledRuleItem, OwnerRiskItem, RiskSeverityLevel

[POS]
Harness framework layer contracts for Swarm Coordination, Memory Recall HUD & Owner Risk Checklist (Item 42 P0).
Strictly under 120 lines. Zero `Any`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

RiskSeverityLevel = Literal["low", "medium", "high", "critical"]


@dataclass(slots=True)
class SwarmModeConfig:
    enabled: bool = False
    concurrency_quota: int = 5
    auto_decompose: bool = True
    session_id: str = ""


@dataclass(slots=True)
class SwarmSubagentTask:
    task_id: str
    role_title: str
    boundary_description: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    current_step: str = ""
    assigned_tools: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecalledRuleItem:
    rule_id: str
    summary: str
    source_turn_id: str
    confidence: float
    is_active: bool = True
    category: str = "business_rule"
    created_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)


@dataclass(slots=True)
class OwnerRiskItem:
    risk_id: str
    title: str
    description: str
    severity: RiskSeverityLevel = "medium"
    is_confirmed: bool = False
    confirmed_by: str = ""
    external_constraint_type: str = "compliance"
    remediation_hint: str = ""
