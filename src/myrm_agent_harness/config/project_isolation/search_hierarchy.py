"""Hierarchical Configuration Resolver with Project Trust Gate Isolation."""

from __future__ import annotations

import logging
from pathlib import Path

from .preflight_validator import PreflightConfigValidator
from .types import (
    ConfigResolutionContext,
    ConfigSourceTier,
    DiagnosticCheckResult,
    MyrmProjectConfigSchema,
)

logger = logging.getLogger(__name__)


class HierarchicalConfigResolver:
    """Resolves effective configuration following strict search order and trust gate isolation.

    Search Order:
    1. Local Project Config (<workspace>/.myrm/config.json):
       ONLY loaded if `is_project_trusted` is True.
       If untrusted, local config is safely ignored to protect against cloned repo poisoning.
    2. Global User Config (~/.myrm/config.json).
    3. Built-in Defaults.
    """

    def __init__(
        self, validator: PreflightConfigValidator | None = None
    ) -> None:
        self.validator = validator or PreflightConfigValidator()

    def resolve(self, ctx: ConfigResolutionContext) -> DiagnosticCheckResult:
        """Resolve effective configuration for the given workspace context."""
        workspace = Path(ctx.workspace_path).resolve()
        local_cfg_path = workspace / ctx.local_config_rel_path

        local_untrusted_rejected = False

        # Step 1: Check Local Project Configuration
        if local_cfg_path.is_file():
            if ctx.is_project_trusted:
                logger.info(
                    "Loading local project config from trusted workspace: %s",
                    local_cfg_path,
                )
                try:
                    content = local_cfg_path.read_text(encoding="utf-8")
                    return self.validator.validate_json_string(
                        content, applied_tier=ConfigSourceTier.LOCAL_PROJECT_TRUSTED
                    )
                except Exception as exc:
                    return DiagnosticCheckResult(
                        is_valid=False,
                        version="unknown",
                        unknown_keys=(),
                        validation_errors=(
                            f"Failed to read local config file '{local_cfg_path}': {exc}",
                        ),
                        applied_tier=ConfigSourceTier.LOCAL_PROJECT_TRUSTED,
                        effective_config=MyrmProjectConfigSchema(),
                        all_mandatory_features_enabled=False,
                    )
            else:
                logger.warning(
                    "[SECURITY] Workspace at '%s' is UNTRUSTED. Ignoring local configuration file '%s' to prevent config injection.",
                    workspace,
                    local_cfg_path,
                )
                local_untrusted_rejected = True

        # Step 2: Check Global User Configuration
        global_path: Path | None = None
        if ctx.global_config_path:
            global_path = Path(ctx.global_config_path).expanduser().resolve()
        else:
            default_global = Path.home() / ".myrm" / "config.json"
            if default_global.is_file():
                global_path = default_global

        if global_path and global_path.is_file():
            try:
                content = global_path.read_text(encoding="utf-8")
                res = self.validator.validate_json_string(
                    content, applied_tier=ConfigSourceTier.GLOBAL_USER
                )
                if local_untrusted_rejected:
                    # Record that untrusted local config was rejected in favor of global
                    return DiagnosticCheckResult(
                        is_valid=res.is_valid,
                        version=res.version,
                        unknown_keys=res.unknown_keys,
                        validation_errors=res.validation_errors,
                        applied_tier=ConfigSourceTier.LOCAL_PROJECT_UNTRUSTED_REJECTED,
                        effective_config=res.effective_config,
                        all_mandatory_features_enabled=res.all_mandatory_features_enabled,
                    )
                return res
            except Exception as exc:
                logger.warning(
                    "Failed to read global config at %s: %s", global_path, exc
                )

        # Step 3: Built-in Defaults
        tier = (
            ConfigSourceTier.LOCAL_PROJECT_UNTRUSTED_REJECTED
            if local_untrusted_rejected
            else ConfigSourceTier.BUILTIN_DEFAULT
        )
        return DiagnosticCheckResult(
            is_valid=True,
            version="1.0",
            unknown_keys=(),
            validation_errors=(),
            applied_tier=tier,
            effective_config=MyrmProjectConfigSchema(),
            all_mandatory_features_enabled=True,
        )
