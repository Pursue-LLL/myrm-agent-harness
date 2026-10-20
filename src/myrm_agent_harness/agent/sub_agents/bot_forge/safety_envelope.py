"""Builder Safety Envelope enforcing permissions attenuation and anti-recursion guards.

[INPUT]
- __future__
- re
- types

[OUTPUT]
- RECURSIVE_CREATION_TOOLS
- SANDBOX_PROHIBITED_TOOLS
- BuilderSafetyViolationError
- BuilderSafetyEnvelope

[POS]
Builder Safety Envelope enforcing permissions attenuation and anti-recursion guards.

"""

from __future__ import annotations

import re

from .types import (
    BotProfileSpec,
    BuilderAuthority,
    OverlapVerdictEnum,
    TeamCompositionSpec,
)

# Prohibited meta-creation tools that would allow uncontrolled recursive self-replication
RECURSIVE_CREATION_TOOLS: set[str] = {
    "bot_forge",
    "create_agent",
    "agent_create",
    "clone_agent",
    "delete_agent",
    "create_team",
    "subagent_spawn",
    "meta_agent_forge",
}

# Tools that violate sandbox safety boundaries
SANDBOX_PROHIBITED_TOOLS: set[str] = {
    "desktop_control_approval",
    "host_kernel_override",
    "raw_root_exec",
}


class BuilderSafetyViolationError(Exception):
    """Raised when a builder attempts to violate permission or recursion boundaries."""


class BuilderSafetyEnvelope:
    """Enforces safety bounds on chat-driven agent and team creation."""

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize agent name to lowercase kebab-case."""
        cleaned = re.sub(r"[^a-zA-Z0-9_\-\s]", "", name.strip().lower())
        return re.sub(r"[\s_]+", "-", cleaned)

    @classmethod
    def validate_profile_safety(
        cls,
        builder: BuilderAuthority,
        spec: BotProfileSpec,
        is_sandbox: bool = False,
    ) -> None:
        """Validate that a bot profile satisfies anti-recursion and permission attenuation."""
        if not builder.can_create_agents:
            raise BuilderSafetyViolationError(f"Builder '{builder.builder_name}' does not possess agent creation authority.")

        # Rule 1: No recursive agent creation tools
        requested_tools_set = set(spec.tools)
        recursive_violations = requested_tools_set.intersection(RECURSIVE_CREATION_TOOLS)
        if recursive_violations:
            raise BuilderSafetyViolationError(
                f"Recursive creation denied: Child bot '{spec.name}' cannot inherit meta-creation tools {list(recursive_violations)}."
            )

        # Rule 2: Sandbox boundary
        if is_sandbox:
            sandbox_violations = requested_tools_set.intersection(SANDBOX_PROHIBITED_TOOLS)
            if sandbox_violations:
                raise BuilderSafetyViolationError(
                    f"Sandbox violation: Tool(s) {list(sandbox_violations)} prohibited in sandboxed environment."
                )

        # Rule 3: Permission attenuation (child tools/skills/mcps must not exceed builder's authority)
        if builder.allowed_tools:
            unauthorized_tools = requested_tools_set.difference(set(builder.allowed_tools))
            if unauthorized_tools:
                raise BuilderSafetyViolationError(
                    f"Permission escalation: Builder '{builder.builder_name}' cannot grant unauthorized tool(s) {list(unauthorized_tools)}."
                )

        if builder.allowed_skills and spec.skills:
            unauthorized_skills = set(spec.skills).difference(set(builder.allowed_skills))
            if unauthorized_skills:
                raise BuilderSafetyViolationError(
                    f"Permission escalation: Builder '{builder.builder_name}' cannot grant unauthorized skill(s) {list(unauthorized_skills)}."
                )

        if builder.allowed_mcps and spec.mcp_servers:
            unauthorized_mcps = set(spec.mcp_servers).difference(set(builder.allowed_mcps))
            if unauthorized_mcps:
                raise BuilderSafetyViolationError(
                    f"Permission escalation: Builder '{builder.builder_name}' cannot grant unauthorized MCP server(s) {list(unauthorized_mcps)}."
                )

    @classmethod
    def validate_team_safety(
        cls,
        builder: BuilderAuthority,
        team_spec: TeamCompositionSpec,
        is_sandbox: bool = False,
    ) -> None:
        """Validate full team composition against size limits and member safety envelopes."""
        total_specialists = len(team_spec.specialists)
        if total_specialists > builder.max_team_members:
            raise BuilderSafetyViolationError(
                f"Team size limit exceeded: Requested {total_specialists} specialists, max allowed is {builder.max_team_members}."
            )

        # Validate lead
        cls.validate_profile_safety(builder, team_spec.lead, is_sandbox=is_sandbox)

        # Validate each specialist
        for specialist in team_spec.specialists:
            cls.validate_profile_safety(builder, specialist, is_sandbox=is_sandbox)

    @classmethod
    def detect_name_and_duty_overlap(
        cls,
        candidate_name: str,
        candidate_purpose: str,
        existing_agents: list[BotProfileSpec],
        duty_similarity_threshold: float = 0.65,
    ) -> tuple[OverlapVerdictEnum, str | None, str | None]:
        """Detect duplicate naming or excessive semantic overlap with existing agents.

        Returns:
            (verdict, conflicting_name, recommendation)
        """
        norm_candidate = cls.normalize_name(candidate_name)

        # 1. Exact or normalized name match check
        for agent in existing_agents:
            if cls.normalize_name(agent.name) == norm_candidate:
                suggested_alt = f"{norm_candidate}-specialist"
                return (
                    OverlapVerdictEnum.DUPLICATE_NAME,
                    agent.name,
                    f"Agent with name '{agent.name}' already exists. Suggest using '{suggested_alt}' or explicit update.",
                )

        # 2. Lexical keyword duty overlap check
        candidate_tokens = cls._extract_keywords(candidate_purpose)
        if not candidate_tokens:
            return OverlapVerdictEnum.UNIQUE, None, None

        for agent in existing_agents:
            agent_tokens = cls._extract_keywords(agent.description)
            if not agent_tokens:
                continue

            intersection = candidate_tokens.intersection(agent_tokens)
            union = candidate_tokens.union(agent_tokens)
            similarity = len(intersection) / len(union) if union else 0.0

            if similarity >= duty_similarity_threshold:
                return (
                    OverlapVerdictEnum.OVERLAPPING_DUTY,
                    agent.name,
                    f"Purpose significantly overlaps with existing agent '{agent.name}' (similarity {similarity:.2f}). Consider delegating to '{agent.name}' or narrowing scope.",
                )

        return OverlapVerdictEnum.UNIQUE, None, None

    @classmethod
    def sanitize_clone_prompt(
        cls,
        original_name: str,
        new_name: str,
        system_prompt: str,
        original_display_name: str | None = None,
    ) -> str:
        """Sanitize cloned system prompts by substituting the original name with the new identity."""
        if not original_name or not new_name or original_name == new_name:
            result = system_prompt
        else:
            pattern = re.compile(rf"\b{re.escape(original_name)}\b", re.IGNORECASE)
            result = pattern.sub(new_name, system_prompt)

        if original_display_name and original_display_name != new_name:
            disp_pattern = re.compile(rf"\b{re.escape(original_display_name)}\b", re.IGNORECASE)
            result = disp_pattern.sub(new_name, result)
            for token in re.findall(r"[a-zA-Z0-9]+", original_display_name):
                if len(token) >= 3 and token.lower() not in {"bot", "agent", "writer", "assistant", "specialist"}:
                    tok_pattern = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
                    result = tok_pattern.sub(new_name, result)

        return result

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Extract meaningful alphanumeric keywords (length >= 4) from text."""
        words = re.findall(r"[a-zA-Z0-9_\-]+", text.lower())
        stopwords = {
            "this", "that", "with", "from", "your", "agent", "will", "have", "been",
            "should", "would", "could", "task", "help", "user", "work", "make",
        }
        return {w for w in words if len(w) >= 4 and w not in stopwords}
