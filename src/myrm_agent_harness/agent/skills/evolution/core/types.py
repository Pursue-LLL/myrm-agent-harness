"""Data types for skill evolution system.

Simplified but complete implementation for skill self-evolution capability.
Focus on real-world utility with 54% less code than OpenSpace while maintaining full functionality.

[INPUT]
- (none)

[OUTPUT]
- EvolutionType: Type of skill evolution action.
- SkillLineage: Simplified lineage tracking.
- SkillRecord: Complete skill record with evolution metadata.
- EvolutionRequest: Request for skill evolution (for concurrent processing). Supports GUI-First force_retry.

[POS]
Data types for skill evolution system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EvolutionType(StrEnum):
    """Type of skill evolution action."""

    FIX = "fix"  # Auto-repair failed/outdated skills
    DERIVED = "derived"  # Optimize/enhance based on user feedback
    CAPTURED = "captured"  # Capture repeated user commands as new skills
    SLICE_EXTRACTION = "slice_extraction"  # Extract from execution trace slice
    OPTIMIZE_DESCRIPTION = "optimize_description"  # Refine description for better matching


class EvolutionLayer(StrEnum):
    """Layer where the skill or harness modification takes place (MAP-Elites Dimension 1)."""

    PROMPT = "prompt"  # Prompt guidelines, rules, persona adjustments
    TOOL_CODE = "tool_code"  # Executable Python/Shell code, scripts, tools
    RUNTIME_CONFIG = "runtime_config"  # Timeout, retries, concurrency, sandbox config
    KNOWLEDGE_RULE = "knowledge_rule"  # Static lookup data, domain constraints, schema


class FailurePathology(StrEnum):
    """Failure pathology category targeted by the patch (MAP-Elites Dimension 2)."""

    PARAM_ERROR = "param_error"  # Missing or invalid arguments
    TIMEOUT_RETRY = "timeout_retry"  # Network or execution timeout, rate limits
    ENV_MISSING = "env_missing"  # Missing binaries, packages, or permissions
    SEMANTIC_MISUSE = "semantic_misuse"  # Wrong tool selection, misinterpretation
    LOGIC_HALLUCINATION = "logic_hallucination"  # Fabricated facts or invalid syntax
    UNHANDLED_EXCEPTION = "unhandled_exception"  # Runtime crash or uncaught error


@dataclass(frozen=True)
class GeneCellKey:
    """Composite coordinate key for MAP-Elites Gene Bank."""

    layer: EvolutionLayer
    pathology: FailurePathology

    def to_key_str(self) -> str:
        return f"{self.layer.value}:{self.pathology.value}"

    @classmethod
    def from_key_str(cls, key_str: str) -> GeneCellKey:
        parts = key_str.split(":", 1)
        if len(parts) == 2:
            try:
                return cls(
                    layer=EvolutionLayer(parts[0]),
                    pathology=FailurePathology(parts[1]),
                )
            except ValueError:
                pass
        return cls(layer=EvolutionLayer.PROMPT, pathology=FailurePathology.UNHANDLED_EXCEPTION)


@dataclass
class GeneEliteRecord:
    """An elite patch candidate stored within a specific MAP-Elites gene cell."""

    cell_key: GeneCellKey
    skill_name: str
    patch_summary: str
    patch_content: str
    fitness_score: float
    verification_proof: VerificationProof | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_key": self.cell_key.to_key_str(),
            "layer": self.cell_key.layer.value,
            "pathology": self.cell_key.pathology.value,
            "skill_name": self.skill_name,
            "patch_summary": self.patch_summary,
            "patch_content": self.patch_content,
            "fitness_score": self.fitness_score,
            "verification_proof": (self.verification_proof.to_dict() if self.verification_proof else None),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GeneEliteRecord:
        key_str = str(
            data.get(
                "cell_key",
                f"{data.get('layer', 'prompt')}:{data.get('pathology', 'unhandled_exception')}",
            )
        )
        proof_data = data.get("verification_proof")
        return cls(
            cell_key=GeneCellKey.from_key_str(key_str),
            skill_name=str(data.get("skill_name", "")),
            patch_summary=str(data.get("patch_summary", "")),
            patch_content=str(data.get("patch_content", "")),
            fitness_score=float(data.get("fitness_score", 0.0)),
            verification_proof=(VerificationProof.from_dict(proof_data) if proof_data else None),
            created_at=(datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()),
        )


class SkillVerificationType(StrEnum):
    """Classification of verification requirements for a skill."""

    CODE_EXECUTABLE = "code_executable"  # Contains Python or Shell code blocks to run
    PROMPT_INSTRUCTION = "prompt_instruction"  # Pure textual or prompt instruction


@dataclass
class VerificationProof:
    """Proof of sandbox execution verification for a skill evolution proposal."""

    is_verified: bool = False
    hollow_detected: bool = False
    blast_radius: dict[str, int] = field(default_factory=lambda: {"files": 0, "lines": 0})
    verification_summary: str = ""
    command_results: list[dict[str, Any]] = field(default_factory=list)
    environment: EnvironmentFingerprint | None = None
    verified_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_verified": self.is_verified,
            "hollow_detected": self.hollow_detected,
            "blast_radius": self.blast_radius,
            "verification_summary": self.verification_summary,
            "command_results": self.command_results,
            "environment": self.environment.to_dict() if self.environment else None,
            "verified_at": self.verified_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationProof:
        return cls(
            is_verified=bool(data.get("is_verified", False)),
            hollow_detected=bool(data.get("hollow_detected", False)),
            blast_radius=data.get("blast_radius", {"files": 0, "lines": 0}),
            verification_summary=str(data.get("verification_summary", "")),
            command_results=data.get("command_results", []),
            environment=(EnvironmentFingerprint.from_dict(data["environment"]) if data.get("environment") else None),
            verified_at=(datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else datetime.now()),
        )


@dataclass
class EnvironmentFingerprint:
    """Environment context for a skill to ensure safe cross-device sharing."""

    os_platform: str = ""  # e.g., "Darwin", "Linux", "Windows"
    os_release: str = ""  # e.g., "21.6.0"
    python_version: str = ""  # e.g., "3.10.12"
    key_dependencies_hash: str = ""  # Hash of core dependencies (optional)
    custom_tags: dict[str, str] = field(default_factory=dict)  # Extensible tags

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_platform": self.os_platform,
            "os_release": self.os_release,
            "python_version": self.python_version,
            "key_dependencies_hash": self.key_dependencies_hash,
            "custom_tags": self.custom_tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnvironmentFingerprint:
        return cls(
            os_platform=data.get("os_platform", ""),
            os_release=data.get("os_release", ""),
            python_version=data.get("python_version", ""),
            key_dependencies_hash=data.get("key_dependencies_hash", ""),
            custom_tags=data.get("custom_tags", {}),
        )


@dataclass
class SkillLineage:
    """Simplified lineage tracking.

    Replaces complex DAG with simple versioning:
    - version: Simple integer version (v1, v2, v3...)
    - parent_id: Single parent skill_id (for FIX/DERIVED)
    - Reduces 5 tables to 1 simple field (95% complexity reduction)
    """

    evolution_type: EvolutionType
    version: int = 1
    parent_id: str | None = None  # None for CAPTURED, skill_id for FIX/DERIVED
    change_summary: str = ""  # LLM-generated description
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""  # Model name or "human"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evolution_type": self.evolution_type.value,
            "version": self.version,
            "parent_id": self.parent_id,
            "change_summary": self.change_summary,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillLineage:
        return cls(
            evolution_type=EvolutionType(data["evolution_type"]),
            version=data.get("version", 1),
            parent_id=data.get("parent_id"),
            change_summary=data.get("change_summary", ""),
            created_at=(datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()),
            created_by=data.get("created_by", ""),
        )


@dataclass
class SkillRecord:
    """Complete skill record with evolution metadata."""

    skill_id: str
    name: str
    description: str
    content: str
    path: str

    lineage: SkillLineage
    environment: EnvironmentFingerprint | None = None

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    is_active: bool = True
    evolution_locked: bool = False

    verification_steps: list[dict[str, Any]] = field(default_factory=list)
    eval_cases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "path": self.path,
            "lineage": self.lineage.to_dict(),
            "environment": self.environment.to_dict() if self.environment else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "evolution_locked": self.evolution_locked,
            "verification_steps": self.verification_steps,
            "eval_cases": self.eval_cases,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRecord:
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data["description"],
            content=data["content"],
            path=data["path"],
            lineage=SkillLineage.from_dict(data["lineage"]),
            environment=(EnvironmentFingerprint.from_dict(data["environment"]) if data.get("environment") else None),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            is_active=data.get("is_active", True),
            evolution_locked=data.get("evolution_locked", False),
            verification_steps=data.get("verification_steps", []),
            eval_cases=data.get("eval_cases", []),
        )


@dataclass
class EvolutionRequest:
    """Request for skill evolution (for concurrent processing)."""

    evolution_type: EvolutionType
    skill_id: str | None = None  # For FIX/DERIVED, None for CAPTURED
    reason: str = ""  # Error message for FIX, user feedback for DERIVED, pattern for CAPTURED
    user_feedback: str = ""  # Optional user feedback for DERIVED
    repeated_commands: list[str] = field(default_factory=list)  # For CAPTURED
    session_id: str = ""  # For SLICE_EXTRACTION
    tool_call_ids: list[str] = field(default_factory=list)  # For SLICE_EXTRACTION
    agent_id: str | None = None  # For SLICE_EXTRACTION
    force_retry: bool = False  # GUI-First explicit flag to bypass cooldowns

    def to_dict(self) -> dict[str, Any]:
        return {
            "evolution_type": self.evolution_type.value,
            "skill_id": self.skill_id,
            "reason": self.reason,
            "user_feedback": self.user_feedback,
            "repeated_commands": self.repeated_commands,
            "session_id": self.session_id,
            "tool_call_ids": self.tool_call_ids,
            "agent_id": self.agent_id,
            "force_retry": self.force_retry,
        }


@dataclass
class EvolutionProposal:
    """Standardized evolution proposal data structure.

    Replaces direct file system modification. A proposal contains variants,
    sandbox test scores, and the suggested unified diff for human/GUI review.
    """

    skill_id: str
    evolution_type: EvolutionType
    original_content: str
    proposed_content: str
    diff: str
    score: float
    reasoning: str
    task_context: str = ""
    trajectory: str = ""  # The detailed trace analysis report
    is_general: bool = False
    environment: EnvironmentFingerprint | None = None
    agent_id: str | None = None
    edit_summary: dict[str, Any] | None = None  # {preserved_sections, changed_sections, notes}
    updated_eval_cases: list[dict[str, Any]] | None = None
    recommended_form: str = "skill"  # "skill" | "cron_job" | "skip"
    form_metadata: dict[str, Any] | None = None  # {schedule_hint, form_reasoning}
    verification_proof: VerificationProof | None = None
    target_layer: EvolutionLayer = EvolutionLayer.PROMPT
    target_pathology: FailurePathology = FailurePathology.UNHANDLED_EXCEPTION
    created_at: datetime = field(default_factory=datetime.now)
    # Result of the security scan ProposalBuilder ran on the proposed content;
    # None when no scan ran (OPTIMIZE_DESCRIPTION proposals carry no skill body).
    security_scan_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "evolution_type": self.evolution_type.value,
            "original_content": self.original_content,
            "proposed_content": self.proposed_content,
            "diff": self.diff,
            "score": self.score,
            "reasoning": self.reasoning,
            "task_context": self.task_context,
            "trajectory": self.trajectory,
            "is_general": self.is_general,
            "environment": self.environment.to_dict() if self.environment else None,
            "agent_id": self.agent_id,
            "edit_summary": self.edit_summary,
            "updated_eval_cases": self.updated_eval_cases,
            "recommended_form": self.recommended_form,
            "form_metadata": self.form_metadata,
            "verification_proof": (self.verification_proof.to_dict() if self.verification_proof else None),
            "target_layer": self.target_layer.value,
            "target_pathology": self.target_pathology.value,
            "created_at": self.created_at.isoformat(),
            "security_scan_summary": self.security_scan_summary,
        }
