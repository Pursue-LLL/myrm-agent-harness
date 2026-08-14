"""Organization-managed approval policy floor (Managed Approval Policy / MAP).

[INPUT]
- Deployment layer injects JSON via MYRM_MANAGED_APPROVAL_POLICY_JSON (optional).

[OUTPUT]
- ManagedApprovalPolicy: frozen policy model + env/process loader

[POS]
Harness SSOT for org floor rules that constrain allowlist honor, YOLO, auto-review,
and allow-always UI. Empty policy = zero behavior change (local/Tauri default).
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

ENV_MANAGED_APPROVAL_POLICY_JSON: Final[str] = "MYRM_MANAGED_APPROVAL_POLICY_JSON"


@dataclass(frozen=True, slots=True)
class ManagedApprovalPolicy:
    """Org floor constraints applied on top of user/agent SecurityConfig."""

    ignore_allowlist_for_models: frozenset[str] = frozenset()
    force_auto_review_for_models: frozenset[str] = frozenset()
    disable_yolo: bool = False
    disable_allow_always: bool = False

    @classmethod
    def empty(cls) -> ManagedApprovalPolicy:
        return cls()

    def matches_model(self, pattern: str, agent_primary_model: str) -> bool:
        slug = agent_primary_model.strip()
        if not slug or not pattern.strip():
            return False
        return fnmatch.fnmatchcase(slug, pattern.strip())

    def should_ignore_allowlist(self, agent_primary_model: str) -> bool:
        if not agent_primary_model.strip():
            return False
        return any(self.matches_model(pattern, agent_primary_model) for pattern in self.ignore_allowlist_for_models)

    def should_force_auto_review(self, agent_primary_model: str) -> bool:
        if not agent_primary_model.strip():
            return False
        return any(self.matches_model(pattern, agent_primary_model) for pattern in self.force_auto_review_for_models)

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> ManagedApprovalPolicy:
        ignore_raw = raw.get("ignoreAllowlistForModels", raw.get("ignore_allowlist_for_models"))
        force_raw = raw.get("forceAutoReviewForModels", raw.get("force_auto_review_for_models"))
        disable_yolo_raw = raw.get("disableYolo", raw.get("disable_yolo", False))
        disable_allow_raw = raw.get("disableAllowAlways", raw.get("disable_allow_always", False))

        return cls(
            ignore_allowlist_for_models=_parse_pattern_set(ignore_raw),
            force_auto_review_for_models=_parse_pattern_set(force_raw),
            disable_yolo=bool(disable_yolo_raw),
            disable_allow_always=bool(disable_allow_raw),
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "ignoreAllowlistForModels": sorted(self.ignore_allowlist_for_models),
            "forceAutoReviewForModels": sorted(self.force_auto_review_for_models),
            "disableYolo": self.disable_yolo,
            "disableAllowAlways": self.disable_allow_always,
        }


_process_policy: ManagedApprovalPolicy = ManagedApprovalPolicy.empty()
_process_revision: int = 0


def _parse_pattern_set(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        return frozenset()
    patterns: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            patterns.append(item.strip())
    return frozenset(patterns)


def configure_process_managed_approval_policy(policy: ManagedApprovalPolicy) -> None:
    """Set process-wide MAP (called from agent-server startup)."""
    global _process_policy, _process_revision
    _process_policy = policy
    _process_revision += 1


def get_process_managed_approval_policy() -> ManagedApprovalPolicy:
    return _process_policy


def get_process_managed_approval_revision() -> int:
    return _process_revision


def load_managed_approval_policy_from_env(
    *,
    env: Mapping[str, str] | None = None,
) -> ManagedApprovalPolicy:
    source = env if env is not None else os.environ
    raw_json = source.get(ENV_MANAGED_APPROVAL_POLICY_JSON, "").strip()
    if not raw_json:
        return ManagedApprovalPolicy.empty()
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.warning("Invalid %s JSON — using empty MAP", ENV_MANAGED_APPROVAL_POLICY_JSON)
        return ManagedApprovalPolicy.empty()
    if not isinstance(parsed, dict):
        logger.warning("%s must be a JSON object — using empty MAP", ENV_MANAGED_APPROVAL_POLICY_JSON)
        return ManagedApprovalPolicy.empty()
    return ManagedApprovalPolicy.from_mapping(parsed)
