# ============================================================================
# Standardized Agent Handoff Brief & State Continuity Bridge Engine (Item 170)
# Orchestrates structured cross-session and cross-agent handoff briefs, preserving
# architectural decisions (what & why), blockers, and instant state continuity.
# ============================================================================

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from .handoff_brief_types import (
    DecisionItem,
    DelegationRoleKind,
    HandoffBrief,
    HandoffIngressResult,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StandardizedAgentHandoffBridge:
    """Gateway orchestrating structured handoff briefs and cross-session state continuity."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # brief_id -> HandoffBrief
        self._briefs: dict[str, HandoffBrief] = {}
        # source_session_id -> latest brief_id
        self._session_latest_brief: dict[str, str] = {}
        # target_session_id -> active HandoffIngressResult
        self._active_handoffs: dict[str, HandoffIngressResult] = {}

    def create_brief(
        self,
        source_session_id: str,
        task_goal: str,
        completed_steps: Sequence[str] = (),
        blocked_points: Sequence[str] = (),
        decisions: Sequence[DecisionItem] = (),
        relevant_files: Sequence[str] = (),
        env_dependencies: Mapping[str, str] | None = None,
    ) -> HandoffBrief:
        """Create and register a standardized cross-session handoff brief."""
        brief_id = f"brief-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        brief = HandoffBrief(
            brief_id=brief_id,
            source_session_id=source_session_id,
            task_goal=task_goal.strip(),
            completed_steps=tuple(completed_steps),
            blocked_points=tuple(blocked_points),
            decisions=tuple(decisions),
            relevant_files=tuple(relevant_files),
            env_dependencies=dict(env_dependencies or {}),
            created_at_iso=now_iso,
        )

        with self._lock:
            self._briefs[brief_id] = brief
            self._session_latest_brief[source_session_id] = brief_id

        logger.info(
            "Created handoff brief '%s' from session '%s' with %d decisions and %d files",
            brief_id,
            source_session_id,
            len(decisions),
            len(relevant_files),
        )
        return brief

    def render_handoff_xml(self, brief: HandoffBrief) -> str:
        """Render dense, structured XML representation for prompt context injection."""
        lines: list[str] = [
            f'<agent_handoff_brief source_session="{brief.source_session_id}" brief_id="{brief.brief_id}">',
            f"  <task_goal>{brief.task_goal}</task_goal>",
        ]

        if brief.completed_steps:
            lines.append("  <completed_milestones>")
            for s in brief.completed_steps:
                lines.append(f"    <item>{s}</item>")
            lines.append("  </completed_milestones>")

        if brief.blocked_points:
            lines.append("  <blocked_points>")
            for b in brief.blocked_points:
                lines.append(f"    <item>{b}</item>")
            lines.append("  </blocked_points>")

        if brief.decisions:
            lines.append("  <architectural_decisions>")
            for d in brief.decisions:
                lines.append(
                    f'    <decision what="{d.what}" why="{d.why}" category="{d.category}" />'
                )
            lines.append("  </architectural_decisions>")

        if brief.relevant_files:
            lines.append("  <relevant_files>")
            for f in sorted(brief.relevant_files):
                lines.append(f"    <file>{f}</file>")
            lines.append("  </relevant_files>")

        if brief.env_dependencies:
            lines.append("  <environment_dependencies>")
            for k in sorted(brief.env_dependencies.keys()):
                lines.append(f'    <env key="{k}" value="{brief.env_dependencies[k]}" />')
            lines.append("  </environment_dependencies>")

        lines.append("</agent_handoff_brief>")
        return "\n".join(lines)

    def import_to_session(
        self,
        target_session_id: str,
        brief: HandoffBrief,
    ) -> HandoffIngressResult:
        """Import handoff brief into a target session, rendering context and recording link."""
        rendered_xml = self.render_handoff_xml(brief)
        token_estimate = max(1, len(rendered_xml) // 4)
        now_iso = _utc_now_iso()

        result = HandoffIngressResult(
            target_session_id=target_session_id,
            brief_id=brief.brief_id,
            source_session_id=brief.source_session_id,
            injected_xml_context=rendered_xml,
            injected_token_estimate=token_estimate,
            applied_at_iso=now_iso,
        )

        with self._lock:
            self._active_handoffs[target_session_id] = result

        logger.info(
            "Imported handoff '%s' to session '%s' (~%d tokens)",
            brief.brief_id,
            target_session_id,
            token_estimate,
        )
        return result

    def create_role_scoped_brief(
        self,
        brief: HandoffBrief,
        target_role: DelegationRoleKind,
    ) -> HandoffBrief:
        """Filter and focus handoff brief contents for specialized subagent delegation."""
        if target_role == DelegationRoleKind.GENERAL_AGENT:
            return brief

        filtered_decisions = list(brief.decisions)
        filtered_files = list(brief.relevant_files)
        filtered_envs = dict(brief.env_dependencies)

        if target_role == DelegationRoleKind.CODE_AUDITOR:
            # Focus on security, architecture, and core source files
            filtered_decisions = [
                d for d in brief.decisions if d.category in ("architecture", "security")
            ]
            filtered_files = [
                f for f in brief.relevant_files if f.endswith((".py", ".ts", ".rs", ".go"))
            ]
        elif target_role == DelegationRoleKind.FRONTEND_SPECIALIST:
            # Focus on frontend UI files and client decisions
            filtered_decisions = [
                d for d in brief.decisions if d.category in ("frontend", "ui", "architecture")
            ]
            filtered_files = [
                f
                for f in brief.relevant_files
                if f.endswith((".tsx", ".ts", ".jsx", ".css", ".vue"))
            ]
        elif target_role == DelegationRoleKind.INFRA_OPS:
            # Focus on env dependencies and deployment files
            filtered_decisions = [
                d for d in brief.decisions if d.category in ("infra", "ops", "architecture")
            ]
            filtered_files = [
                f
                for f in brief.relevant_files
                if f.endswith((".yml", ".yaml", ".dockerfile", ".toml", ".sh"))
            ]

        scoped_id = f"{brief.brief_id}-{target_role.value}"
        scoped_brief = HandoffBrief(
            brief_id=scoped_id,
            source_session_id=brief.source_session_id,
            task_goal=f"[{target_role.value.upper()}] {brief.task_goal}",
            completed_steps=brief.completed_steps,
            blocked_points=brief.blocked_points,
            decisions=tuple(filtered_decisions),
            relevant_files=tuple(filtered_files),
            env_dependencies=filtered_envs,
            created_at_iso=_utc_now_iso(),
        )

        with self._lock:
            self._briefs[scoped_id] = scoped_brief

        return scoped_brief

    def get_brief(self, brief_id: str) -> HandoffBrief | None:
        """Retrieve stored brief by unique brief ID."""
        with self._lock:
            return self._briefs.get(brief_id)

    def get_session_active_handoff(
        self,
        target_session_id: str,
    ) -> HandoffIngressResult | None:
        """Fetch active handoff ingress result for a target session."""
        with self._lock:
            return self._active_handoffs.get(target_session_id)
