"""Strategic advisor schema and compilation utilities.

[INPUT]
- pydantic::BaseModel, Field, field_validator (POS: Pydantic v2 schema building blocks)

[OUTPUT]
- StrategicIdentitySchema: Role and description schema for strategic advisor identity
- StrategicScopeSchema: Read-only scope definition with tools allowlist and denylist
- StrategicOutputProtocolSchema: Structured reporting and output formatting schema
- StrategicAdvisorySchema: 4-section declarative strategic advisor schema
- READONLY_FORBIDDEN_TOOLS: Frozenset of side-effect and write tools forbidden in read-only mode
- validate_strategic_readonly_safety(): Enforces zero write capabilities in read-only advisory scope
- compile_strategic_advisor_prompt(): Compiles 4-section schema into structured system prompt

[POS]
Declarative 4-section schema specification for bundled strategic advisor subagents,
guaranteeing unsycophantic pushback, strict read-only execution boundaries, and
structured architecture directives.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

READONLY_FORBIDDEN_TOOLS: frozenset[str] = frozenset(
    {
        "file_write_tool",
        "file_edit_tool",
        "bash_code_execute_tool",
        "skill_manage_tool",
        "skill_market_tool",
        "invoke_acp_agent_tool",
        "cron_manage_tool",
    }
)


class StrategicIdentitySchema(BaseModel):
    """Identity specification for strategic advisory subagents."""

    role: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)


class StrategicScopeSchema(BaseModel):
    """Execution scope enforcing read-only boundary."""

    mode: Literal["readonly"] = "readonly"
    tools: list[str] = Field(default_factory=list)
    disallowed_tools: list[str] = Field(default_factory=list)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v != "readonly":
            raise ValueError(f"Strategic advisor scope must be 'readonly', received '{v}'")
        return v


class StrategicOutputProtocolSchema(BaseModel):
    """Structured report format contract."""

    format: str = Field(default="markdown", max_length=50)
    required_sections: list[str] = Field(
        default_factory=lambda: [
            "Executive Summary",
            "Critical Architectural Flaws & Trade-offs",
            "Alternative Designs & Impact Analysis",
            "Actionable Strategic Directives",
        ]
    )


class StrategicAdvisorySchema(BaseModel):
    """Declarative 4-section schema for strategic advisor subagents.

    Sections:
    1. identity: role and unsycophantic persona
    2. scope: strict read-only inspection boundary
    3. advisory_principles: architectural and engineering review principles
    4. output_protocol: structured output sections
    """

    identity: StrategicIdentitySchema
    scope: StrategicScopeSchema = Field(default_factory=StrategicScopeSchema)
    advisory_principles: list[str] = Field(min_length=1)
    output_protocol: StrategicOutputProtocolSchema = Field(
        default_factory=StrategicOutputProtocolSchema
    )


def validate_strategic_readonly_safety(
    scope: StrategicScopeSchema,
    tools: list[str],
) -> None:
    """Enforce fail-closed security for read-only strategic advisor tools.

    Raises:
        ValueError: If any forbidden write/mutation tool is found in active tools.
    """
    if scope.mode != "readonly":
        raise ValueError(f"Scope mode must be 'readonly', got '{scope.mode}'")

    forbidden_found = sorted(set(tools) & READONLY_FORBIDDEN_TOOLS)
    if forbidden_found:
        raise ValueError(
            f"Read-only strategic advisor cannot possess write/mutation tools: {forbidden_found}"
        )


def compile_strategic_advisor_prompt(advisory: StrategicAdvisorySchema) -> str:
    """Compile declarative 4-section schema into a cohesive, unsycophantic system prompt."""
    principles_lines = "\n".join(f"- {principle}" for principle in advisory.advisory_principles)
    sections_lines = "\n".join(f"- {section}" for section in advisory.output_protocol.required_sections)

    return (
        f"You are {advisory.identity.role}.\n"
        f"{advisory.identity.description}\n\n"
        f"OPERATIONAL SCOPE & BOUNDARY:\n"
        f"- Strict read-only mode ({advisory.scope.mode}). You NEVER write or mutate files or state.\n"
        f"- Gather evidence via read and search tools only. Every claim must cite concrete evidence.\n\n"
        f"STRATEGIC ADVISORY PRINCIPLES:\n"
        f"{principles_lines}\n\n"
        f"OUTPUT PROTOCOL:\n"
        f"Format: {advisory.output_protocol.format}\n"
        f"You MUST structure your strategic advice into the following required sections:\n"
        f"{sections_lines}\n"
    )
