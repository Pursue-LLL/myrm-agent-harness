"""[POS]: src/myrm_agent_harness/toolkits/memory/job_compounding/job_builder.py
[INPUT]: Domain parameters, tool assignments, work styles, and approval boundaries.
[OUTPUT]: JobDescriptionBuilder validating specs, evaluating action boundaries, and rendering prompt contracts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .models import ApprovalBoundarySpec, JobDescriptionSpec

_DEFAULT_MUTATION_CUES: tuple[str, ...] = (
    "send", "publish", "delete", "purchase", "pay", "deploy", "overwrite",
    "modify", "invite", "terminate", "drop", "commit",
)


class JobDescriptionBuilder:
    """Builds, validates, and evaluates domain-specific job description specifications."""

    @classmethod
    def build_spec(
        cls,
        agent_id: str,
        job_title: str,
        target_scope: str,
        tools_and_sources: list[str] | None = None,
        work_style: str = "rigorous",
        autonomous_actions: list[str] | None = None,
        requires_approval_actions: list[str] | None = None,
    ) -> JobDescriptionSpec:
        """Constructs a validated 4-pillar job description spec."""
        cleaned_agent_id = agent_id.strip()
        cleaned_title = job_title.strip()
        cleaned_scope = target_scope.strip()

        if not cleaned_agent_id or not cleaned_title or not cleaned_scope:
            raise ValueError("agent_id, job_title, and target_scope must not be empty.")

        boundary = ApprovalBoundarySpec(
            autonomous_actions=[a.strip().lower() for a in (autonomous_actions or []) if a.strip()],
            requires_approval_actions=[
                a.strip().lower() for a in (requires_approval_actions or []) if a.strip()
            ],
        )

        return JobDescriptionSpec(
            agent_id=cleaned_agent_id,
            job_title=cleaned_title,
            target_scope=cleaned_scope,
            tools_and_sources=[t.strip() for t in (tools_and_sources or []) if t.strip()],
            work_style=work_style.strip(),
            approval_boundary=boundary,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    @classmethod
    def evaluate_action_boundary(
        cls,
        spec: JobDescriptionSpec,
        action_name: str,
    ) -> tuple[bool, str]:
        """Evaluates whether an action requires explicit human sign-off (HITL escalation).

        Returns:
            (needs_approval: bool, reason: str)
        """
        normalized_action = action_name.strip().lower()

        # 1. Explicit requires approval check takes highest precedence
        for req in spec.approval_boundary.requires_approval_actions:
            if req in normalized_action or re.search(r"\b" + re.escape(req) + r"\b", normalized_action):
                return True, f"Action explicitly listed under requires_approval_actions: {req}"

        # 2. Explicit autonomous actions check
        for auto in spec.approval_boundary.autonomous_actions:
            if auto in normalized_action or re.search(r"\b" + re.escape(auto) + r"\b", normalized_action):
                return False, f"Action permitted by autonomous_actions: {auto}"

        # 3. Default safety heuristics: mutation cues require approval by default
        for cue in _DEFAULT_MUTATION_CUES:
            if cue in normalized_action:
                return True, f"High-stakes mutation detected ({cue}) without explicit autonomous grant"

        return False, "Standard query or safe inspection permitted autonomously"

    @classmethod
    def render_system_contract(cls, spec: JobDescriptionSpec) -> str:
        """Renders the 4-pillar job description spec into a rigid system prompt contract."""
        tools_str = ", ".join(spec.tools_and_sources) if spec.tools_and_sources else "Standard Toolset"
        auto_actions_str = ", ".join(spec.approval_boundary.autonomous_actions) or "Read-only inspection and drafting"
        req_actions_str = ", ".join(spec.approval_boundary.requires_approval_actions) or "External mutations, payments, and releases"

        return (
            f"## Role Job Description: {spec.job_title} (Agent ID: {spec.agent_id})\n\n"
            f"### 1. Target Scope & Goal\n{spec.target_scope}\n\n"
            f"### 2. Tools & Sources\n{tools_str}\n\n"
            f"### 3. Work Style & Tone\n{spec.work_style}\n\n"
            f"### 4. Approval Boundaries\n"
            f"- **Autonomous Execution Permitted**: {auto_actions_str}\n"
            f"- **Strict Human Approval Required**: {req_actions_str}\n"
        )
