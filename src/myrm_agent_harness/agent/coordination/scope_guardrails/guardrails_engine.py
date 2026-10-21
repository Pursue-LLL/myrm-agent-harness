"""Scope Guardrails and Safe Team Design Mode verification engine.

[INPUT]
- Candidate team roles with requested toolsets and SafeTeamDesignConfig parameters.

[OUTPUT]
- ScopeGuardrailsEngine evaluating least-privilege bounds, enforcing fan-out caps,
  and sanitizing tool permissions.

[POS]
- Harness coordination layer permission verification engine for multi-agent squads.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.coordination.scope_guardrails.types import (
    MemberScopeCandidate,
    SafeTeamDesignConfig,
    ScopeViolationFinding,
    TeamGuardrailsEvaluationResult,
    ViolationSeverity,
    ViolationType,
)

logger = logging.getLogger(__name__)


class ScopeGuardrailsEngine:
    """Verifies proposed squad designs against least-privilege role boundaries and fan-out limits."""

    def __init__(self, default_config: SafeTeamDesignConfig | None = None) -> None:
        self._default_config = default_config or SafeTeamDesignConfig()

    def evaluate_team_design(
        self,
        candidates: list[MemberScopeCandidate],
        config: SafeTeamDesignConfig | None = None,
    ) -> TeamGuardrailsEvaluationResult:
        """Audit candidate squad against scope guardrails, capping fan-out and sanitizing tools."""
        cfg = config or self._default_config
        original_count = len(candidates)
        violations: list[ScopeViolationFinding] = []
        fanout_capped = False

        # 1. Check fan-out cap
        approved_candidates: list[MemberScopeCandidate]
        if original_count > cfg.max_fanout_cap:
            fanout_capped = True
            excess = original_count - cfg.max_fanout_cap
            violations.append(
                ScopeViolationFinding(
                    role_key="squad_root",
                    tool_name="spawn_subagent",
                    violation_type=ViolationType.FANOUT_LIMIT_EXCEEDED,
                    severity=ViolationSeverity.BLOCKER,
                    recommendation=(
                        f"Squad size {original_count} exceeds safe fan-out cap ({cfg.max_fanout_cap}). "
                        f"Truncated {excess} excess descendant role(s) to avoid orchestrator exhaustion."
                    ),
                )
            )
            approved_candidates = candidates[: cfg.max_fanout_cap]
        else:
            approved_candidates = list(candidates)

        # 2. Inspect and sanitize requested tools per approved role
        sanitized_tools_map: dict[str, list[str]] = {}

        for member in approved_candidates:
            clean_tools: list[str] = []
            role_allowlist = cfg.role_tool_allowlists.get(member.role_key)

            for tool in member.requested_tools:
                tool_clean = tool.strip()
                if not tool_clean:
                    continue

                # Check 2a: Globally forbidden tools
                if tool_clean in cfg.forbidden_tools:
                    violations.append(
                        ScopeViolationFinding(
                            role_key=member.role_key,
                            tool_name=tool_clean,
                            violation_type=ViolationType.FORBIDDEN_TOOL,
                            severity=ViolationSeverity.BLOCKER,
                            recommendation=(
                                f"Tool '{tool_clean}' is globally forbidden for autonomous subagent delegation. "
                                f"Stripped from '{member.role_key}'."
                            ),
                        )
                    )
                    continue

                # Check 2b: Role least-privilege boundary
                if role_allowlist is not None and tool_clean not in role_allowlist:
                    violations.append(
                        ScopeViolationFinding(
                            role_key=member.role_key,
                            tool_name=tool_clean,
                            violation_type=ViolationType.ROLE_SCOPE_EXCEEDED,
                            severity=ViolationSeverity.WARNING,
                            recommendation=(
                                f"Tool '{tool_clean}' exceeds least-privilege allowlist for role '{member.role_key}'. "
                                f"Automatically stripped in safe design mode."
                            ),
                        )
                    )
                    continue

                clean_tools.append(tool_clean)

            sanitized_tools_map[member.role_key] = clean_tools

        # 3. Determine safety disposition
        has_blockers = any(v.severity == ViolationSeverity.BLOCKER for v in violations)
        is_safe = (not has_blockers) and (not fanout_capped)

        # 4. Formulate audit summary
        if is_safe and not violations:
            summary = (
                f"Squad design passed all scope guardrails. All {len(approved_candidates)} roles adhere "
                f"to minimum necessary privileges."
            )
        elif is_safe:
            summary = (
                f"Squad design approved with {len(violations)} non-blocking scope warning(s). "
                f"Tools converged to safe subset."
            )
        else:
            blocker_count = sum(1 for v in violations if v.severity == ViolationSeverity.BLOCKER)
            summary = (
                f"Squad design flagged with {blocker_count} blocker(s) and {len(violations)} total violation(s). "
                f"Sanitized fallback blueprint prepared."
            )

        logger.info(
            "Evaluated squad design (%d roles): safe=%s, violations=%d",
            original_count,
            is_safe,
            len(violations),
        )

        return TeamGuardrailsEvaluationResult(
            is_safe=is_safe,
            sanitized_tools_map=sanitized_tools_map,
            violations=violations,
            fanout_capped=fanout_capped,
            original_member_count=original_count,
            approved_member_count=len(approved_candidates),
            audit_summary=summary,
        )
