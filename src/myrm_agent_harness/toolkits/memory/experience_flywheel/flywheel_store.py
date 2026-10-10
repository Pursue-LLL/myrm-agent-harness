"""Causal Flywheel Store for engineering experiences and architectural decisions.

[INPUT]
- EngineeringExperience records, workspace paths, and target entity queries.

[OUTPUT]
- CausalFlywheelStore: manages experience persistence, entity bindings, and dongle synchronization.

[POS]
- Flywheel storage and binding engine for Item 154 ProjectExperienceAndADRFlywheelSuite.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.project_dongle import (
    DongleBlock,
    DongleBlockType,
    ProjectContextDongleManager,
)

from .models import EngineeringExperience, ExperienceKind, FlywheelIngestResult


class CausalFlywheelStore:
    """Stores engineering experiences with entity bindings and syncs to worktree dongles."""

    def __init__(self, dongle_manager: ProjectContextDongleManager | None = None) -> None:
        self.dongle_manager = dongle_manager or ProjectContextDongleManager()
        # Primary storage: experience_id -> EngineeringExperience
        self._store: dict[str, EngineeringExperience] = {}
        # Entity index: target_entity.lower() -> list of experience_ids
        self._entity_index: dict[str, list[str]] = {}

    def ingest_experience(
        self,
        experience: EngineeringExperience,
        workspace_dir: str | Path | None = None,
    ) -> FlywheelIngestResult:
        """Ingest an experience record, update entity bindings, and optionally sync to dongle."""
        self._store[experience.experience_id] = experience

        entity_key = experience.target_entity.lower()
        if entity_key not in self._entity_index:
            self._entity_index[entity_key] = []
        if experience.experience_id not in self._entity_index[entity_key]:
            self._entity_index[entity_key].append(experience.experience_id)

        bound_block_id: str | None = None

        # Optionally sync to dongle files
        if workspace_dir:
            ws_path = Path(workspace_dir)
            target_file_type = (
                DongleBlockType.DECISIONS
                if experience.kind == ExperienceKind.ARCHITECTURAL_DECISION
                else DongleBlockType.LESSONS
            )

            bullet_content = (
                f"[{experience.target_entity}] Trigger: {experience.trigger_condition} | "
                f"Cause: {experience.root_cause_or_rationale} | "
                f"Convention: {experience.convention_or_remedy}"
            )
            dongle_block = DongleBlock(
                block_id=experience.experience_id,
                block_type=target_file_type,
                content=bullet_content,
                created_date=experience.created_date,
                tags=(experience.target_entity.lower(), experience.kind.value),
            )
            self.dongle_manager.append_block(ws_path, dongle_block)
            bound_block_id = experience.experience_id

        return FlywheelIngestResult(
            experience_id=experience.experience_id,
            kind=experience.kind,
            target_entity=experience.target_entity,
            bound_dongle_block_id=bound_block_id,
            persisted=True,
            message="Ingested into engineering knowledge flywheel.",
        )

    def find_by_entity(self, entity_name: str) -> list[EngineeringExperience]:
        """Lookup all experiences bound to a specific entity."""
        exp_ids = self._entity_index.get(entity_name.lower(), [])
        return [self._store[i] for i in exp_ids if i in self._store]

    def list_all(self, kind: ExperienceKind | None = None) -> list[EngineeringExperience]:
        """List all experiences, optionally filtered by kind."""
        if kind is None:
            return list(self._store.values())
        return [e for e in self._store.values() if e.kind == kind]

    def count(self) -> int:
        """Return total count of ingested experiences."""
        return len(self._store)
