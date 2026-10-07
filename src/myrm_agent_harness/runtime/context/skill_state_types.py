from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from enum import StrEnum


class PrebuiltStateSchemaKind(StrEnum):
    """Five standard industrial-grade pre-built state schemas."""

    SOFTWARE_REPOSITORY = "software_repository"
    REVERSE_ENGINEERING = "reverse_engineering"
    RESOURCE_INVENTORY = "resource_inventory"
    BUSINESS_TRANSACTION = "business_transaction"
    CODING_BUGFIX_LOOP = "coding_bugfix_loop"


@dataclass(frozen=True)
class ConstantPromptTuple:
    """Core constant prompt tuple (P + Sigma_t + O_t) for SKILL.state runtime."""

    spec_prompt: str
    state_table: dict[str, object]
    latest_observation: str | None = None

    def render_prompt(self) -> str:
        """Render constant prompt with structured XML blocks."""
        state_json = json.dumps(self.state_table, ensure_ascii=False, indent=2, sort_keys=True)
        parts: list[str] = [
            f"<system_specification>\n{self.spec_prompt.strip()}\n</system_specification>",
            f"<skill_state_table>\n{state_json}\n</skill_state_table>",
        ]
        if self.latest_observation is not None:
            parts.append(
                f"<latest_observation>\n{self.latest_observation.strip()}\n</latest_observation>"
            )
        return "\n\n".join(parts)


@dataclass(frozen=True)
class StateMergePatch:
    """RFC 7386 JSON Merge Patch payload with optional schema target and rationale."""

    patch_dict: dict[str, object]
    target_schema_id: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class AuditLogEventRecord:
    """Immutable audit record stored in background append-only log."""

    step_index: int
    timestamp_iso: str
    action: str
    observation_raw: str
    state_snapshot: dict[str, object]
    patch_applied: dict[str, object]
    rationale: str | None = None


@dataclass(frozen=True)
class RetroactiveProbeQuery:
    """Query parameter for retroactive observation retrieval probe."""

    keyword: str
    step_index_min: int | None = None
    step_index_max: int | None = None


@dataclass(frozen=True)
class RetroactiveProbeResult:
    """Result returned by the retroactive audit probe."""

    matched_records: list[AuditLogEventRecord] = field(default_factory=list)
    suggested_patch: dict[str, object] | None = None


def get_default_schema_state(schema_kind: PrebuiltStateSchemaKind) -> dict[str, object]:
    """Factory creating initial state tables for the 5 industrial standard schemas."""
    if schema_kind == PrebuiltStateSchemaKind.SOFTWARE_REPOSITORY:
        return {
            "current_branch": "main",
            "modified_files": [],
            "pr_dependencies": [],
            "ci_matrix_status": {"build": "pending", "test": "pending"},
            "active_tasks": [],
        }
    elif schema_kind == PrebuiltStateSchemaKind.REVERSE_ENGINEERING:
        return {
            "discovered_flags": [],
            "validated_hypotheses": [],
            "falsified_hypotheses": [],
            "target_binaries": [],
            "active_workdir": "/workspace",
        }
    elif schema_kind == PrebuiltStateSchemaKind.RESOURCE_INVENTORY:
        return {
            "allocated_slots": {},
            "inventory_items": [],
            "transfer_queue": [],
            "quota_limits": {"max_slots": 100, "used_slots": 0},
        }
    elif schema_kind == PrebuiltStateSchemaKind.BUSINESS_TRANSACTION:
        return {
            "user_profile": {"tier": "standard"},
            "cart_items": [],
            "applied_promotions": [],
            "transaction_status": "draft",
            "policy_constraints": [],
        }
    elif schema_kind == PrebuiltStateSchemaKind.CODING_BUGFIX_LOOP:
        return {
            "target_files": [],
            "reproducing_test_passed": False,
            "hypothesis_chain": [],
            "refactoring_steps": [],
            "verified_fixes": [],
        }
    return {}


def clone_state(state: dict[str, object]) -> dict[str, object]:
    """Create a deep copy of a state table dictionary."""
    return copy.deepcopy(state)
