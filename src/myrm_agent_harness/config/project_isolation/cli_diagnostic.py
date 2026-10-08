"""Preflight Diagnostic Runner Engine."""

from __future__ import annotations

import logging
from pathlib import Path

from .preflight_validator import PreflightConfigValidator
from .search_hierarchy import HierarchicalConfigResolver
from .types import (
    ConfigResolutionContext,
    ConfigSourceTier,
    DiagnosticCheckResult,
    MyrmProjectConfigSchema,
)

logger = logging.getLogger(__name__)


def run_preflight_diagnostics(
    *,
    config_path: str | None = None,
    workspace_path: str | None = None,
    is_trusted: bool = False,
    require_all_enabled: bool = False,
) -> DiagnosticCheckResult:
    """Run preflight diagnostics on a target config file or workspace.

    Args:
        config_path: Direct path to a config JSON file to validate.
        workspace_path: Workspace directory to resolve hierarchically.
        is_trusted: Whether the workspace is marked as trusted.
        require_all_enabled: Hard assert that all mandatory security features are enabled.

    Returns:
        DiagnosticCheckResult indicating whether the configuration is valid and safe.
    """
    validator = PreflightConfigValidator(require_all_enabled=require_all_enabled)

    # Mode 1: Direct File Preflight Validation
    if config_path:
        target = Path(config_path).expanduser().resolve()
        if not target.is_file():
            return DiagnosticCheckResult(
                is_valid=False,
                version="unknown",
                unknown_keys=(),
                validation_errors=(f"Config file not found: {target}",),
                applied_tier=ConfigSourceTier.LOCAL_PROJECT_TRUSTED,
                effective_config=MyrmProjectConfigSchema(),
                all_mandatory_features_enabled=False,
            )
        try:
            content = target.read_text(encoding="utf-8")
            return validator.validate_json_string(
                content, applied_tier=ConfigSourceTier.LOCAL_PROJECT_TRUSTED
            )
        except Exception as exc:
            return DiagnosticCheckResult(
                is_valid=False,
                version="unknown",
                unknown_keys=(),
                validation_errors=(f"Failed to read '{target}': {exc}",),
                applied_tier=ConfigSourceTier.LOCAL_PROJECT_TRUSTED,
                effective_config=MyrmProjectConfigSchema(),
                all_mandatory_features_enabled=False,
            )

    # Mode 2: Workspace Hierarchical Resolution
    ws_dir = workspace_path or "."
    ctx = ConfigResolutionContext(
        workspace_path=ws_dir,
        is_project_trusted=is_trusted,
    )
    resolver = HierarchicalConfigResolver(validator=validator)
    return resolver.resolve(ctx)
