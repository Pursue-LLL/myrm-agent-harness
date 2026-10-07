"""Strongly typed domain models for L3 World Model macro context and project environment.

[POS]
src/myrm_agent_harness/toolkits/memory/world_model/models.py
Defines the four-dimensional macro entity model (safety rules, project environment,
architecture contract, domain knowledge) and compact prompt serialization contracts.

[INPUT]
- enum: StrEnum
- dataclasses: dataclass, field
- typing: List, Dict, Optional

[OUTPUT]
- L3WorldModelField: Enumeration of four macro dimensions.
- RuntimeEnvironmentInfo: Detected language/runtime profile.
- ProjectEnvironmentSnapshot: Multi-runtime project environment footprint.
- L3WorldModelRecord: Aggregate macro state entity with optimistic versioning.
- MacroContextPayload: Immutable prompt context injection packet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class L3WorldModelField(StrEnum):
    """The four canonical dimensions of L3 World Model macro memory."""

    GENERAL_RULES = "general_rules_and_safety_constraints"
    PROJECT_ENVIRONMENT = "project_environment_profile"
    PROJECT_CONTRACT = "project_contract"
    DOMAIN_KNOWLEDGE = "domain_knowledge"


@dataclass(frozen=True)
class RuntimeEnvironmentInfo:
    """Specific runtime or language toolchain descriptor."""

    name: str
    version: str
    package_manager: str
    key_dependencies: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectEnvironmentSnapshot:
    """Aggregated project environment footprint across multiple runtimes."""

    workspace_name: str
    runtimes: list[RuntimeEnvironmentInfo] = field(default_factory=list)
    config_markers: list[str] = field(default_factory=list)
    detected_at: float = 0.0


@dataclass
class L3WorldModelRecord:
    """Core entity state representing L3 World Model for a project workspace."""

    project_id: str
    version: int = 1
    updated_at: float = 0.0
    general_rules: str = ""
    project_environment: str = ""
    project_contract: str = ""
    domain_knowledge: str = ""
    source_refs: list[str] = field(default_factory=list)

    def get_dimension(self, field_name: L3WorldModelField) -> str:
        """Retrieve content for a specific macro dimension."""
        mapping: dict[L3WorldModelField, str] = {
            L3WorldModelField.GENERAL_RULES: self.general_rules,
            L3WorldModelField.PROJECT_ENVIRONMENT: self.project_environment,
            L3WorldModelField.PROJECT_CONTRACT: self.project_contract,
            L3WorldModelField.DOMAIN_KNOWLEDGE: self.domain_knowledge,
        }
        return mapping.get(field_name, "")

    def set_dimension(self, field_name: L3WorldModelField, content: str) -> None:
        """Update content for a specific macro dimension."""
        if field_name == L3WorldModelField.GENERAL_RULES:
            self.general_rules = content
        elif field_name == L3WorldModelField.PROJECT_ENVIRONMENT:
            self.project_environment = content
        elif field_name == L3WorldModelField.PROJECT_CONTRACT:
            self.project_contract = content
        elif field_name == L3WorldModelField.DOMAIN_KNOWLEDGE:
            self.domain_knowledge = content


@dataclass(frozen=True)
class MacroContextPayload:
    """Serialized top-level context packet ready for LLM System Prompt injection."""

    project_id: str
    version: int
    rendered_markdown: str
    field_breakdown: dict[str, str]
    token_estimate: int
    has_active_constraints: bool
