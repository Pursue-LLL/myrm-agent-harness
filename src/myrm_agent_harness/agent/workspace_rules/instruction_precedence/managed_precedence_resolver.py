"""Precedence resolver enforcing managed settings supremacy and denying repository authority.

[INPUT]
- agent.workspace_rules.instruction_precedence.precedence_types::InstructionMode, InstructionSettings,
  ResolvedPrecedence, SettingsScope (POS: Strongly typed contracts for project instruction modes and managed
  precedence.)

[OUTPUT]
- ManagedPrecedenceResolver: Evaluates hierarchical settings scopes where managed policies strictly override
  local configs.

[POS]
Precedence resolver enforcing managed settings supremacy and denying repository authority.
"""

from __future__ import annotations

from .precedence_types import (
    InstructionMode,
    InstructionSettings,
    ResolvedPrecedence,
    SettingsScope,
)


class ManagedPrecedenceResolver:
    """Evaluates hierarchical settings scopes where managed policies strictly override local configs."""

    def resolve_precedence(
        self,
        managed_settings: InstructionSettings | None = None,
        user_settings: InstructionSettings | None = None,
        cli_flags: InstructionSettings | None = None,
        repo_settings: InstructionSettings | None = None,
    ) -> ResolvedPrecedence:
        """Resolve effective instruction mode following Managed > User > CLI precedence.

        Crucial invariant: Repository-level configurations (.claude/settings.json or .myrm/settings.json)
        have zero authority to decide or override the project instruction mode.
        """
        repo_override_rejected = False
        if repo_settings is not None:
            # Repository attempt to set instruction mode is explicitly ignored and flagged
            repo_override_rejected = True

        effective_managed_instructions: list[str] = []
        if managed_settings and managed_settings.managed_instructions:
            effective_managed_instructions.extend(managed_settings.managed_instructions)
        elif user_settings and user_settings.managed_instructions:
            effective_managed_instructions.extend(user_settings.managed_instructions)
        elif cli_flags and cli_flags.managed_instructions:
            effective_managed_instructions.extend(cli_flags.managed_instructions)

        # 1. Managed Settings: Absolute top priority
        if managed_settings is not None and managed_settings.scope == SettingsScope.MANAGED_SETTINGS:
            return ResolvedPrecedence(
                effective_mode=managed_settings.mode,
                origin_scope=SettingsScope.MANAGED_SETTINGS,
                repo_override_rejected=repo_override_rejected,
                effective_managed_instructions=effective_managed_instructions,
            )

        # 2. User Settings: Second priority
        if user_settings is not None and user_settings.scope == SettingsScope.USER_SETTINGS:
            return ResolvedPrecedence(
                effective_mode=user_settings.mode,
                origin_scope=SettingsScope.USER_SETTINGS,
                repo_override_rejected=repo_override_rejected,
                effective_managed_instructions=effective_managed_instructions,
            )

        # 3. CLI Flags / Runtime options: Third priority
        if cli_flags is not None and cli_flags.scope == SettingsScope.CLI_FLAGS:
            return ResolvedPrecedence(
                effective_mode=cli_flags.mode,
                origin_scope=SettingsScope.CLI_FLAGS,
                repo_override_rejected=repo_override_rejected,
                effective_managed_instructions=effective_managed_instructions,
            )

        # Default fallback: ALL_MERGED (preserves our superior multi-file merge capabilities)
        return ResolvedPrecedence(
            effective_mode=InstructionMode.ALL_MERGED,
            origin_scope=SettingsScope.USER_SETTINGS,
            repo_override_rejected=repo_override_rejected,
            effective_managed_instructions=effective_managed_instructions,
        )
