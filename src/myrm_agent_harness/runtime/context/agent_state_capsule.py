"""Universal Agent State Capsule & Cross-Device Migration Bundle Engine.

Provides atomic encapsulation of agent profile, custom skills, hierarchical memories,
and session checkpoints into a portable, integrity-verified capsule (.myrmagent)
with deterministic conflict resolution and environment validation.

[INPUT]
- runtime.context.agent_state_capsule_types::AgentProfileCapsule, CapsuleEnvironmentDiagnostic,
  CapsuleHeader, CapsuleIntegrityError, CapsuleMergeStrategy, MemoryCapsuleEntry, ResolvedMigrationBundle,
  SessionCheckpointCapsuleEntry, +2 more (POS: Data contracts and models for Universal Agent State Capsule.)

[OUTPUT]
- CapsuleMigrationResolver: Pre-flight diagnostics and multi-strategy migration resolution.
- CapsuleSerializationEngine: Serializes, deserializes, and verifies portable agent state capsules.

[POS]
Universal Agent State Capsule & Cross-Device Migration Bundle Engine.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from typing import ClassVar

from myrm_agent_harness.runtime.context.agent_state_capsule_types import (
    AgentProfileCapsule,
    CapsuleEnvironmentDiagnostic,
    CapsuleHeader,
    CapsuleIntegrityError,
    CapsuleMergeStrategy,
    MemoryCapsuleEntry,
    ResolvedMigrationBundle,
    SessionCheckpointCapsuleEntry,
    SkillCapsuleEntry,
    UniversalAgentCapsule,
)

__all__ = [
    "AgentProfileCapsule",
    "CapsuleEnvironmentDiagnostic",
    "CapsuleHeader",
    "CapsuleIntegrityError",
    "CapsuleMergeStrategy",
    "CapsuleMigrationResolver",
    "CapsuleSerializationEngine",
    "MemoryCapsuleEntry",
    "ResolvedMigrationBundle",
    "SessionCheckpointCapsuleEntry",
    "SkillCapsuleEntry",
    "UniversalAgentCapsule",
]


class CapsuleSerializationEngine:
    """Serializes, deserializes, and verifies portable agent state capsules."""

    @staticmethod
    def _compute_sha256(canonical_payload: str) -> str:
        return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    @classmethod
    def _build_body_dict(
        cls,
        *,
        schema_version: str,
        capsule_id: str,
        created_at_utc: str,
        source_host: str,
        encryption_algo: str,
        profile_dict: dict[str, object],
        skills: list[dict[str, object]],
        memories: list[dict[str, object]],
        checkpoints: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "schema_version": schema_version,
            "capsule_id": capsule_id,
            "created_at_utc": created_at_utc,
            "source_host": source_host,
            "encryption_algo": encryption_algo,
            "profile": profile_dict,
            "skills": skills,
            "memories": memories,
            "checkpoints": checkpoints,
        }

    @classmethod
    def create_capsule(
        cls,
        *,
        capsule_id: str,
        created_at_utc: str,
        source_host: str,
        profile: AgentProfileCapsule,
        skills: tuple[SkillCapsuleEntry, ...],
        memories: tuple[MemoryCapsuleEntry, ...],
        checkpoints: tuple[SessionCheckpointCapsuleEntry, ...],
        schema_version: str = "1.0.0",
        encryption_algo: str = "NONE",
    ) -> UniversalAgentCapsule:
        body = cls._build_body_dict(
            schema_version=schema_version,
            capsule_id=capsule_id,
            created_at_utc=created_at_utc,
            source_host=source_host,
            encryption_algo=encryption_algo,
            profile_dict=asdict(profile),
            skills=[asdict(s) for s in skills],
            memories=[asdict(m) for m in memories],
            checkpoints=[asdict(c) for c in checkpoints],
        )
        canonical_str = json.dumps(body, sort_keys=True, separators=(",", ":"))
        checksum = cls._compute_sha256(canonical_str)
        header = CapsuleHeader(
            schema_version=schema_version,
            capsule_id=capsule_id,
            created_at_utc=created_at_utc,
            source_host=source_host,
            checksum_sha256=checksum,
            encryption_algo=encryption_algo,
        )
        return UniversalAgentCapsule(header=header, profile=profile, skills=skills, memories=memories, checkpoints=checkpoints)

    @classmethod
    def to_json(cls, capsule: UniversalAgentCapsule) -> str:
        data: dict[str, object] = {
            "header": asdict(capsule.header),
            "profile": asdict(capsule.profile),
            "skills": [asdict(s) for s in capsule.skills],
            "memories": [asdict(m) for m in capsule.memories],
            "checkpoints": [asdict(c) for c in capsule.checkpoints],
        }
        return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw_json: str, *, verify_integrity: bool = True) -> UniversalAgentCapsule:
        raw = json.loads(raw_json)
        h_raw, p_raw = raw.get("header"), raw.get("profile")
        if not isinstance(h_raw, dict) or not isinstance(p_raw, dict):
            raise CapsuleIntegrityError("Missing header or profile in capsule payload")

        claimed_sum = str(h_raw.get("checksum_sha256", ""))
        body = cls._build_body_dict(
            schema_version=str(h_raw.get("schema_version", "1.0.0")),
            capsule_id=str(h_raw.get("capsule_id", "")),
            created_at_utc=str(h_raw.get("created_at_utc", "")),
            source_host=str(h_raw.get("source_host", "")),
            encryption_algo=str(h_raw.get("encryption_algo", "NONE")),
            profile_dict=p_raw,
            skills=raw.get("skills", []),
            memories=raw.get("memories", []),
            checkpoints=raw.get("checkpoints", []),
        )

        if verify_integrity:
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
            if cls._compute_sha256(canonical) != claimed_sum:
                raise CapsuleIntegrityError(f"Integrity checksum mismatch: claimed {claimed_sum}")

        header = CapsuleHeader(
            schema_version=str(h_raw.get("schema_version", "1.0.0")),
            capsule_id=str(h_raw.get("capsule_id", "")),
            created_at_utc=str(h_raw.get("created_at_utc", "")),
            source_host=str(h_raw.get("source_host", "")),
            checksum_sha256=claimed_sum,
            encryption_algo=str(h_raw.get("encryption_algo", "NONE")),
        )
        profile = AgentProfileCapsule(
            agent_id=str(p_raw.get("agent_id", "")),
            name=str(p_raw.get("name", "")),
            description=str(p_raw.get("description", "")),
            system_prompt=str(p_raw.get("system_prompt", "")),
            model_provider=str(p_raw.get("model_provider", "")),
            model_name=str(p_raw.get("model_name", "")),
            temperature=float(p_raw.get("temperature", 0.7)),
            max_tokens=int(p_raw.get("max_tokens", 4096)),
            metadata={str(k): str(v) for k, v in p_raw.get("metadata", {}).items()},
        )
        skills = tuple(
            SkillCapsuleEntry(
                skill_id=str(s.get("skill_id", "")),
                name=str(s.get("name", "")),
                description=str(s.get("description", "")),
                code_or_config=str(s.get("code_or_config", "")),
                mcp_server_ref=str(s.get("mcp_server_ref", "")),
                enabled=bool(s.get("enabled", True)),
            )
            for s in raw.get("skills", [])
        )
        memories = tuple(
            MemoryCapsuleEntry(
                memory_id=str(m.get("memory_id", "")),
                memory_type=str(m.get("memory_type", "episodic")),
                content=str(m.get("content", "")),
                importance=float(m.get("importance", 1.0)),
                tags=tuple(str(t) for t in m.get("tags", ())),
                created_at_utc=str(m.get("created_at_utc", "")),
                embedding_vector=tuple(float(x) for x in m["embedding_vector"]) if isinstance(m.get("embedding_vector"), (list, tuple)) else None,
            )
            for m in raw.get("memories", [])
        )
        checkpoints = tuple(
            SessionCheckpointCapsuleEntry(
                session_id=str(c.get("session_id", "")),
                epoch_index=int(c.get("epoch_index", 0)),
                summary_text=str(c.get("summary_text", "")),
                created_at_utc=str(c.get("created_at_utc", "")),
            )
            for c in raw.get("checkpoints", [])
        )
        return UniversalAgentCapsule(header=header, profile=profile, skills=skills, memories=memories, checkpoints=checkpoints)


class CapsuleMigrationResolver:
    """Pre-flight diagnostics and multi-strategy migration resolution."""

    _KEY_MAP: ClassVar[dict[str, str]] = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }

    @classmethod
    def diagnose_environment(
        cls,
        capsule: UniversalAgentCapsule,
        *,
        available_env_vars: set[str],
        available_tools: set[str],
    ) -> CapsuleEnvironmentDiagnostic:
        missing_env: list[str] = []
        missing_tools: list[str] = []
        warnings: list[str] = []

        prov = capsule.profile.model_provider.lower()
        if prov in cls._KEY_MAP and cls._KEY_MAP[prov] not in available_env_vars:
            missing_env.append(cls._KEY_MAP[prov])
            warnings.append(f"Model provider '{prov}' missing {cls._KEY_MAP[prov]}")

        for s in capsule.skills:
            if s.mcp_server_ref and s.mcp_server_ref not in available_tools:
                missing_tools.append(s.mcp_server_ref)
                warnings.append(f"Missing MCP tool reference: {s.mcp_server_ref}")

        return CapsuleEnvironmentDiagnostic(
            missing_env_vars=tuple(missing_env),
            missing_tools=tuple(missing_tools),
            warnings=tuple(warnings),
            is_ready=len(missing_env) == 0 and len(missing_tools) == 0,
        )

    @classmethod
    def resolve_migration(
        cls,
        capsule: UniversalAgentCapsule,
        *,
        existing_profile: AgentProfileCapsule | None,
        existing_skills: tuple[SkillCapsuleEntry, ...],
        existing_memories: tuple[MemoryCapsuleEntry, ...],
        existing_checkpoints: tuple[SessionCheckpointCapsuleEntry, ...],
        strategy: CapsuleMergeStrategy,
        id_generator: Callable[[str], str] | None = None,
    ) -> ResolvedMigrationBundle:
        actions: list[str] = []
        gen = id_generator or (lambda base: f"{base}_imported")

        if strategy == CapsuleMergeStrategy.CREATE_NEW or existing_profile is None:
            new_id = gen(capsule.profile.agent_id) if existing_profile is not None else capsule.profile.agent_id
            new_prof = AgentProfileCapsule(
                agent_id=new_id,
                name=f"{capsule.profile.name} (Imported)" if existing_profile is not None else capsule.profile.name,
                description=capsule.profile.description,
                system_prompt=capsule.profile.system_prompt,
                model_provider=capsule.profile.model_provider,
                model_name=capsule.profile.model_name,
                temperature=capsule.profile.temperature,
                max_tokens=capsule.profile.max_tokens,
                metadata=dict(capsule.profile.metadata),
            )
            skills = tuple(
                SkillCapsuleEntry(
                    skill_id=gen(s.skill_id) if existing_profile is not None else s.skill_id,
                    name=s.name,
                    description=s.description,
                    code_or_config=s.code_or_config,
                    mcp_server_ref=s.mcp_server_ref,
                    enabled=s.enabled,
                )
                for s in capsule.skills
            )
            mems = tuple(
                MemoryCapsuleEntry(
                    memory_id=gen(m.memory_id) if existing_profile is not None else m.memory_id,
                    memory_type=m.memory_type,
                    content=m.content,
                    importance=m.importance,
                    tags=m.tags,
                    created_at_utc=m.created_at_utc,
                    embedding_vector=m.embedding_vector,
                )
                for m in capsule.memories
            )
            actions.append(f"Created isolated agent '{new_id}'.")
            return ResolvedMigrationBundle(
                profile=new_prof, skills=skills, memories=mems,
                checkpoints=capsule.checkpoints, strategy_applied=CapsuleMergeStrategy.CREATE_NEW,
                actions_taken=tuple(actions),
            )

        if strategy == CapsuleMergeStrategy.OVERWRITE:
            actions.append(f"Overwrote agent '{existing_profile.agent_id}' entirely.")
            return ResolvedMigrationBundle(
                profile=capsule.profile, skills=capsule.skills, memories=capsule.memories,
                checkpoints=capsule.checkpoints, strategy_applied=CapsuleMergeStrategy.OVERWRITE,
                actions_taken=tuple(actions),
            )

        # INCREMENTAL_MERGE
        actions.append(f"Incrementally merged assets into '{existing_profile.agent_id}'.")
        existing_names = {s.name for s in existing_skills}
        merged_skills = list(existing_skills)
        for s in capsule.skills:
            if s.name not in existing_names:
                merged_skills.append(s)
                actions.append(f"Added skill '{s.name}'.")

        existing_hashes = {hashlib.sha256(m.content.encode("utf-8")).hexdigest() for m in existing_memories}
        merged_mems = list(existing_memories)
        for m in capsule.memories:
            h = hashlib.sha256(m.content.encode("utf-8")).hexdigest()
            if h not in existing_hashes:
                merged_mems.append(m)
                existing_hashes.add(h)
                actions.append(f"Appended novel memory '{m.memory_id}'.")

        merged_ckpts = list(existing_checkpoints) + list(capsule.checkpoints)
        merged_ckpts.sort(key=lambda c: c.epoch_index)
        return ResolvedMigrationBundle(
            profile=existing_profile, skills=tuple(merged_skills), memories=tuple(merged_mems),
            checkpoints=tuple(merged_ckpts), strategy_applied=CapsuleMergeStrategy.INCREMENTAL_MERGE,
            actions_taken=tuple(actions),
        )
