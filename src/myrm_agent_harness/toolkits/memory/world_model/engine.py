"""L3 World Model execution engine providing macro entity management and compact serialization.

[POS]
src/myrm_agent_harness/toolkits/memory/world_model/engine.py
Implements the core state machine for storing, updating, merging, and rendering
macro-level project world models with strict budget caps and isolated boundary markers.

[INPUT]
- .models: (L3WorldModelField, L3WorldModelRecord, MacroContextPayload, ProjectEnvironmentSnapshot)
- time: time

[OUTPUT]
- L3WorldModelEngine: Engine executing L3 state operations and rendering macro context.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.world_model.models import (
    L3WorldModelField,
    L3WorldModelRecord,
    MacroContextPayload,
    ProjectEnvironmentSnapshot,
)


class L3WorldModelEngine:
    """Core memory engine managing macro-level project architecture and environment entities."""

    def __init__(self, max_token_budget: int = 1200) -> None:
        self._records: dict[str, L3WorldModelRecord] = {}
        self._max_token_budget = max_token_budget

    def get_or_create_record(self, project_id: str) -> L3WorldModelRecord:
        """Fetch existing world model record or initialize an empty baseline."""
        clean_id = project_id.strip() or "default_project"
        if clean_id not in self._records:
            self._records[clean_id] = L3WorldModelRecord(
                project_id=clean_id,
                version=1,
                updated_at=time.time(),
            )
        return self._records[clean_id]

    def update_dimension(
        self,
        project_id: str,
        field_name: L3WorldModelField,
        content: str,
        source_ref: str | None = None,
    ) -> L3WorldModelRecord:
        """Atomically update a specific dimension, bumping version and record timestamp."""
        record = self.get_or_create_record(project_id)
        record.set_dimension(field_name, content.strip())
        record.version += 1
        record.updated_at = time.time()
        if source_ref and source_ref not in record.source_refs:
            record.source_refs.append(source_ref)
        return record

    def merge_environment_snapshot(
        self,
        project_id: str,
        snapshot: ProjectEnvironmentSnapshot,
        source_ref: str = "environment_probe",
    ) -> L3WorldModelRecord:
        """Format and integrate a ProjectEnvironmentSnapshot into project_environment field."""
        lines: list[str] = [
            f"Workspace: {snapshot.workspace_name}",
        ]
        if snapshot.runtimes:
            lines.append("Detected Runtimes & Toolchains:")
            for r in snapshot.runtimes:
                deps_summary = f" (Key deps: {', '.join(r.key_dependencies)})" if r.key_dependencies else ""
                lines.append(f"- {r.name} {r.version} via {r.package_manager}{deps_summary}")
        if snapshot.config_markers:
            lines.append(f"Configuration Baselines: {', '.join(snapshot.config_markers)}")

        formatted_env = "\n".join(lines)
        return self.update_dimension(
            project_id=project_id,
            field_name=L3WorldModelField.PROJECT_ENVIRONMENT,
            content=formatted_env,
            source_ref=source_ref,
        )

    def render_macro_context(self, project_id: str) -> MacroContextPayload:
        """Assemble an immutable macro-context prompt block encased in boundary delimiters."""
        record = self.get_or_create_record(project_id)
        sections: list[str] = []
        breakdown: dict[str, str] = {}

        # 1. General Rules (Highest Priority)
        rules = record.get_dimension(L3WorldModelField.GENERAL_RULES).strip()
        if rules:
            sections.append(f"#### Global Governance & Safety Constraints:\n{rules}")
            breakdown[L3WorldModelField.GENERAL_RULES.value] = rules

        # 2. Project Environment Profile
        env = record.get_dimension(L3WorldModelField.PROJECT_ENVIRONMENT).strip()
        if env:
            sections.append(f"#### Project Environment Baseline:\n{env}")
            breakdown[L3WorldModelField.PROJECT_ENVIRONMENT.value] = env

        # 3. Project Contract & Architecture
        contract = record.get_dimension(L3WorldModelField.PROJECT_CONTRACT).strip()
        if contract:
            sections.append(f"#### Architecture Topology & Contract:\n{contract}")
            breakdown[L3WorldModelField.PROJECT_CONTRACT.value] = contract

        # 4. Domain Knowledge
        domain = record.get_dimension(L3WorldModelField.DOMAIN_KNOWLEDGE).strip()
        if domain:
            sections.append(f"#### Domain Knowledge & Standards:\n{domain}")
            breakdown[L3WorldModelField.DOMAIN_KNOWLEDGE.value] = domain

        has_active = bool(sections)
        if has_active:
            body = "\n\n".join(sections)
            rendered = (
                "<!-- L3_WORLD_MODEL_BEGIN -->\n"
                f"### [L3 Project Macro World Model · {record.project_id} (v{record.version})]\n"
                "The following architecture topology, environment baselines, and safety rules "
                "represent immutable project ground truths. Adhere strictly to these constraints:\n\n"
                f"{body}\n"
                "<!-- L3_WORLD_MODEL_END -->"
            )
        else:
            rendered = (
                "<!-- L3_WORLD_MODEL_BEGIN -->\n"
                f"### [L3 Project Macro World Model · {record.project_id} (v{record.version})]\n"
                "[NO_MACRO_CONSTRAINTS_DEFINED]\n"
                "<!-- L3_WORLD_MODEL_END -->"
            )

        # Rough token estimate: 1 token ~= 4 characters
        token_estimate = max(1, len(rendered) // 4)

        return MacroContextPayload(
            project_id=record.project_id,
            version=record.version,
            rendered_markdown=rendered,
            field_breakdown=breakdown,
            token_estimate=token_estimate,
            has_active_constraints=has_active,
        )
