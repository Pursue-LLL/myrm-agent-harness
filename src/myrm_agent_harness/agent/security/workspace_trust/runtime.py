"""Apply resolved workspace trust into run-scoped ContextVars.

[INPUT]
- context::set_workspace_trust_level, set_repo_command_prefixes (POS: ContextVar runtime trust)
- provider::resolve_workspace_trust_level (POS: fail-closed trust resolution)
- repo_policy::load_repo_command_prefixes (POS: optional .myrm/config.toml prefixes)

[OUTPUT]
- apply_workspace_trust_for_root: bind trust level + repo prefixes for one workspace root
- clear_workspace_trust_runtime: reset trust ContextVars at run end

[POS]
Run lifecycle bridge — called from setup_workspace / cleanup_run only.
"""

from __future__ import annotations

import logging

from .context import (
    clear_workspace_trust_context,
    set_repo_command_prefixes,
    set_workspace_trust_level,
)
from .provider import resolve_workspace_trust_level
from .repo_policy import load_repo_command_prefixes
from .types import WorkspaceTrustLevel

logger = logging.getLogger(__name__)


def apply_workspace_trust_for_root(workspace_root: str) -> WorkspaceTrustLevel:
    """Resolve and bind workspace trust for the active agent run."""
    level = resolve_workspace_trust_level(workspace_root)
    set_workspace_trust_level(level)
    if level == WorkspaceTrustLevel.TRUSTED:
        prefixes = load_repo_command_prefixes(workspace_root)
        set_repo_command_prefixes(prefixes)
        if prefixes:
            logger.debug(
                "Workspace trust: loaded %d repo command prefix(es) for %s",
                len(prefixes),
                workspace_root,
            )
    else:
        set_repo_command_prefixes(())
    return level


def clear_workspace_trust_runtime() -> None:
    """Reset trust-related ContextVars after an agent run."""
    clear_workspace_trust_context()
