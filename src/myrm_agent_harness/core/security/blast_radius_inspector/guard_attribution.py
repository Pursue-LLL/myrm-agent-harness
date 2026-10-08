"""Guard attribution matrix and least-privilege policy auto-repairer."""

from __future__ import annotations

import logging
import secrets

from myrm_agent_harness.core.security.blast_radius_inspector.types import (
    ActionSurfaceDimension,
    GuardAttributionItem,
    GuardStatus,
    RepairPolicyPatch,
    SinkVulnerabilityItem,
)

logger = logging.getLogger(__name__)


class GuardAttributionEngine:
    """Attributes sinks to active policy guardrails and synthesizes auto-repair least-privilege patches."""

    def attribute_guards(
        self,
        sinks: list[SinkVulnerabilityItem],
        active_guards: dict[str, str],  # sink_id or dimension -> guard_type (e.g. 'HITL', 'PATH_RESTRICTION')
    ) -> list[GuardAttributionItem]:
        """Map each sink against active guardrails to determine whether it is adequately protected."""
        attributed_items: list[GuardAttributionItem] = []

        for sink in sinks:
            guard_name = (
                active_guards.get(sink.sink_identifier)
                or active_guards.get(sink.dimension.value)
                or active_guards.get("GLOBAL")
            )

            if guard_name:
                attributed_items.append(
                    GuardAttributionItem(
                        sink=sink,
                        guard_status=GuardStatus.GUARD_ATTRIBUTED,
                        assigned_guard_name=guard_name,
                        recommended_policy_fix=None,
                    )
                )
            else:
                recommended_fix = self._determine_recommended_fix(sink)
                attributed_items.append(
                    GuardAttributionItem(
                        sink=sink,
                        guard_status=GuardStatus.UNGUARDED_CRITICAL,
                        assigned_guard_name=None,
                        recommended_policy_fix=recommended_fix,
                    )
                )

        return attributed_items

    @staticmethod
    def _determine_recommended_fix(sink: SinkVulnerabilityItem) -> str:
        match sink.dimension:
            case ActionSurfaceDimension.SENDS:
                return "Inject Human-In-The-Loop (HITL) prompt before dispatching outbound communications."
            case ActionSurfaceDimension.FILES:
                return "Apply scoped PathRestrictionPolicy locking access strictly to /workspace sandbox."
            case ActionSurfaceDimension.APIS:
                return "Attach domain allowlist guardrail restricting outbound calls to verified hosts."
            case ActionSurfaceDimension.TOOLS:
                return "Constrain execution mode with ephemeral sub-sandbox isolation."

    def synthesize_repair_patches(
        self,
        attributed_items: list[GuardAttributionItem],
    ) -> list[RepairPolicyPatch]:
        """Synthesize concrete machine-readable policy patches for all unguarded sinks."""
        patches: list[RepairPolicyPatch] = []

        for item in attributed_items:
            if item.guard_status == GuardStatus.UNGUARDED_CRITICAL:
                sink = item.sink
                patch_id = f"patch-{secrets.token_hex(6)}"

                match sink.dimension:
                    case ActionSurfaceDimension.SENDS:
                        guard_type = "HITL"
                        config = {"approval_mode": "ASK_USER_PER_SEND", "timeout_seconds": "300"}
                        rationale = f"Require explicit human authorization before executing {sink.sink_identifier}."
                    case ActionSurfaceDimension.FILES:
                        guard_type = "PATH_RESTRICTION"
                        config = {"allowed_root": "/workspace", "prohibit_symlink_traversal": "true"}
                        rationale = f"Confine file operations for {sink.sink_identifier} to workspace."
                    case ActionSurfaceDimension.APIS:
                        guard_type = "DOMAIN_ALLOWLIST"
                        config = {"mode": "STRICT_ALLOWLIST", "default_action": "BLOCK"}
                        rationale = f"Enforce host domain boundary for external endpoint {sink.sink_identifier}."
                    case ActionSurfaceDimension.TOOLS:
                        guard_type = "SANDBOX_ISOLATION"
                        config = {"container_ephemeral": "true", "read_only_root": "true"}
                        rationale = f"Wrap execution of {sink.sink_identifier} in read-only sandbox."

                patches.append(
                    RepairPolicyPatch(
                        patch_id=patch_id,
                        target_sink=sink.sink_identifier,
                        injected_guard_type=guard_type,
                        patch_configuration=config,
                        rationale=rationale,
                    )
                )

        return patches
