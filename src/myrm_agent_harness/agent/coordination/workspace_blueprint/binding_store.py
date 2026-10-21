"""Thread-safe storage and resolution engine for Project Workspace Team Blueprint Auto-Reuse.

[INPUT]
- WorkspaceBlueprintBinding registrations, workspace resolution requests, and usage records.

[OUTPUT]
- WorkspaceBlueprintStore providing thread-safe workspace binding, auto-reuse policy checks,
  and LRU recent template recommendations.

[POS]
- Harness coordination core engine for per-project team template reuse.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from myrm_agent_harness.agent.coordination.workspace_blueprint.types import (
    AutoReusePolicy,
    WorkspaceBlueprintBinding,
    WorkspaceBlueprintResolution,
)

logger = logging.getLogger(__name__)


class WorkspaceBlueprintStore:
    """Thread-safe engine managing workspace-to-blueprint mappings and auto-reuse rules."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bindings: dict[str, WorkspaceBlueprintBinding] = {}
        self._usage_lru: list[str] = []

    def bind_blueprint(
        self,
        workspace_id: str,
        blueprint_id: str,
        team_name: str,
        auto_reuse_policy: AutoReusePolicy = AutoReusePolicy.PROMPT_REUSE,
        member_count: int = 0,
        total_budget_tokens: int = 0,
        project_label: str = "",
        blueprint_snapshot: dict[str, str | int | float | bool] | None = None,
    ) -> WorkspaceBlueprintBinding:
        """Bind or update a team blueprint for a specific workspace."""
        if not workspace_id.strip():
            msg = "workspace_id cannot be blank"
            raise ValueError(msg)
        if not blueprint_id.strip():
            msg = "blueprint_id cannot be blank"
            raise ValueError(msg)
        if not team_name.strip():
            msg = "team_name cannot be blank"
            raise ValueError(msg)

        now = datetime.now(tz=UTC)
        binding = WorkspaceBlueprintBinding(
            workspace_id=workspace_id.strip(),
            blueprint_id=blueprint_id.strip(),
            team_name=team_name.strip(),
            auto_reuse_policy=auto_reuse_policy,
            bound_at=now,
            last_used_at=now,
            member_count=max(0, member_count),
            total_budget_tokens=max(0, total_budget_tokens),
            project_label=project_label.strip(),
            blueprint_snapshot=dict(blueprint_snapshot or {}),
        )

        with self._lock:
            self._bindings[binding.workspace_id] = binding
            if binding.workspace_id in self._usage_lru:
                self._usage_lru.remove(binding.workspace_id)
            self._usage_lru.append(binding.workspace_id)

        logger.info(
            "Bound blueprint %s to workspace %s with policy %s",
            blueprint_id,
            workspace_id,
            auto_reuse_policy.value,
        )
        return binding

    def resolve_blueprint(self, workspace_id: str) -> WorkspaceBlueprintResolution:
        """Resolve the team blueprint configuration and auto-reuse disposition for a workspace."""
        normalized_ws = workspace_id.strip()
        with self._lock:
            binding = self._bindings.get(normalized_ws)

            if binding is not None:
                if binding.auto_reuse_policy == AutoReusePolicy.ALWAYS_REUSE:
                    return WorkspaceBlueprintResolution(
                        workspace_id=normalized_ws,
                        binding=binding,
                        can_auto_instantiate=True,
                        status_label="auto_instantiable",
                        resolution_rationale=(
                            f"Workspace '{normalized_ws}' is bound to team '{binding.team_name}' "
                            f"with ALWAYS_REUSE policy."
                        ),
                    )
                if binding.auto_reuse_policy == AutoReusePolicy.PROMPT_REUSE:
                    return WorkspaceBlueprintResolution(
                        workspace_id=normalized_ws,
                        binding=binding,
                        can_auto_instantiate=False,
                        status_label="prompt_candidate",
                        resolution_rationale=(
                            f"Workspace '{normalized_ws}' has bound team '{binding.team_name}'. "
                            f"Prompt user to confirm reuse before instantiation."
                        ),
                    )
                return WorkspaceBlueprintResolution(
                    workspace_id=normalized_ws,
                    binding=binding,
                    can_auto_instantiate=False,
                    status_label="manual_only",
                    resolution_rationale=(
                        f"Workspace '{normalized_ws}' team '{binding.team_name}' is set to MANUAL_ONLY."
                    ),
                )

            # Unbound: check for most recently used blueprint as fallback recommendation
            recent_binding = self.get_most_recent_binding()
            if recent_binding is not None:
                return WorkspaceBlueprintResolution(
                    workspace_id=normalized_ws,
                    binding=recent_binding,
                    can_auto_instantiate=False,
                    status_label="unbound_recommend_recent",
                    resolution_rationale=(
                        f"Workspace '{normalized_ws}' is unbound. Recommending most recently used "
                        f"team blueprint '{recent_binding.team_name}' from workspace '{recent_binding.workspace_id}'."
                    ),
                )

            return WorkspaceBlueprintResolution(
                workspace_id=normalized_ws,
                binding=None,
                can_auto_instantiate=False,
                status_label="unbound_no_template",
                resolution_rationale=f"Workspace '{normalized_ws}' has no bound blueprint or history.",
            )

    def record_usage(self, workspace_id: str) -> bool:
        """Mark a workspace blueprint as recently used."""
        normalized_ws = workspace_id.strip()
        with self._lock:
            binding = self._bindings.get(normalized_ws)
            if binding is None:
                return False

            now = datetime.now(tz=UTC)
            updated = WorkspaceBlueprintBinding(
                workspace_id=binding.workspace_id,
                blueprint_id=binding.blueprint_id,
                team_name=binding.team_name,
                auto_reuse_policy=binding.auto_reuse_policy,
                bound_at=binding.bound_at,
                last_used_at=now,
                member_count=binding.member_count,
                total_budget_tokens=binding.total_budget_tokens,
                project_label=binding.project_label,
                blueprint_snapshot=dict(binding.blueprint_snapshot),
            )
            self._bindings[normalized_ws] = updated
            if normalized_ws in self._usage_lru:
                self._usage_lru.remove(normalized_ws)
            self._usage_lru.append(normalized_ws)
            return True

    def unbind_blueprint(self, workspace_id: str) -> bool:
        """Remove blueprint binding from a workspace."""
        normalized_ws = workspace_id.strip()
        with self._lock:
            if normalized_ws in self._bindings:
                del self._bindings[normalized_ws]
                if normalized_ws in self._usage_lru:
                    self._usage_lru.remove(normalized_ws)
                logger.info("Unbound blueprint from workspace %s", normalized_ws)
                return True
            return False

    def get_binding(self, workspace_id: str) -> WorkspaceBlueprintBinding | None:
        """Get the direct binding for a workspace if present."""
        with self._lock:
            return self._bindings.get(workspace_id.strip())

    def list_bindings(self) -> list[WorkspaceBlueprintBinding]:
        """List all active workspace bindings ordered by last_used_at descending."""
        with self._lock:
            return sorted(
                self._bindings.values(),
                key=lambda b: b.last_used_at,
                reverse=True,
            )

    def get_most_recent_binding(self) -> WorkspaceBlueprintBinding | None:
        """Fetch the most recently used binding across all workspaces."""
        with self._lock:
            if not self._usage_lru:
                return None
            most_recent_ws = self._usage_lru[-1]
            return self._bindings.get(most_recent_ws)

    def clear(self) -> None:
        """Clear all workspace bindings and LRU history."""
        with self._lock:
            self._bindings.clear()
            self._usage_lru.clear()
