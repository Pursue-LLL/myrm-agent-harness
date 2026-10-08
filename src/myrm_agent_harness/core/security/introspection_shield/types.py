"""
[POS] src/myrm_agent_harness/core/security/introspection_shield/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] IntrospectionProbeType, DecoupledTemplateStandard, ShieldActionEnum, ProbeEvaluationResult, HydratedTemplateRecord, IntrospectionShieldMetrics

Data structures and specifications for Agent Runtime Introspection Shield & Decoupled Workspace Template Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntrospectionProbeType(StrEnum):
    """Categorized runtime introspection probe attack vectors."""

    HOST_PATH_PROBE = "HOST_PATH_PROBE"
    SYSTEM_CONFIG_INSPECTION = "SYSTEM_CONFIG_INSPECTION"
    ENVIRONMENT_LEAK_PROBE = "ENVIRONMENT_LEAK_PROBE"
    FRAMEWORK_SOURCE_SNOOPING = "FRAMEWORK_SOURCE_SNOOPING"
    CONTAINER_TOPOLOGY_PROBE = "CONTAINER_TOPOLOGY_PROBE"


class DecoupledTemplateStandard(StrEnum):
    """Standardized decoupled workspace persona, preference, and runtime contract files."""

    SOUL = "SOUL"
    USER = "USER"
    IDENTITY = "IDENTITY"
    BOOTSTRAP = "BOOTSTRAP"
    HEARTBEAT = "HEARTBEAT"


class ShieldActionEnum(StrEnum):
    """Action taken by the introspection shield upon probe evaluation."""

    ALLOW_UNRESTRICTED = "ALLOW_UNRESTRICTED"
    BLOCK_BLACKHOLE = "BLOCK_BLACKHOLE"
    FAKE_ROOT_REDIRECT = "FAKE_ROOT_REDIRECT"
    SANITIZE_MASK = "SANITIZE_MASK"


@dataclass(frozen=True)
class ProbeEvaluationResult:
    """Security verdict returned after evaluating an execution path or resource access probe."""

    is_blocked: bool
    probe_type: IntrospectionProbeType | None
    attempted_target: str
    action_taken: ShieldActionEnum
    sanitized_path: str
    explanation: str
    timestamp: float


@dataclass(frozen=True)
class HydratedTemplateRecord:
    """Descriptor of a hydrated decoupled workspace specification file."""

    standard: DecoupledTemplateStandard
    filename: str
    content: str
    source_path: str
    is_active: bool
    character_count: int


@dataclass
class IntrospectionShieldMetrics:
    """Operational metrics tracking introspection defenses and template hydration."""

    probes_evaluated: int = 0
    probes_blocked: int = 0
    fake_root_redirects: int = 0
    templates_hydrated: int = 0
    scaffolds_generated: int = 0
