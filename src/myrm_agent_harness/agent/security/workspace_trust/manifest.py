"""Build pre-bind workspace trust manifests for FolderGate disclosure."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from .repo_policy import load_repo_command_prefixes
from .types import WorkspaceTrustLevel, WorkspaceTrustManifest

logger = logging.getLogger(__name__)


def canonicalize_workspace_path(raw_path: str) -> str:
    """Expand and resolve a workspace bind path for registry keys."""
    trimmed = raw_path.strip()
    if not trimmed:
        return ""
    expanded = os.path.expanduser(trimmed)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        raise ValueError("workspace path must be absolute")
    return str(candidate.resolve())


def _count_workspace_skills(workspace_root: str) -> int:
    try:
        from myrm_agent_harness.backends.skills.local import scan_workspace_skills

        return len(scan_workspace_skills(workspace_root, use_snapshot=False, disclosure_only=True))
    except Exception as exc:
        logger.debug("workspace trust manifest: skill scan failed: %s", exc)
        return 0


def _count_workspace_rules(workspace_root: str) -> int:
    try:
        from myrm_agent_harness.agent.workspace_rules.scanner import scan_workspace_rules

        return len(scan_workspace_rules(workspace_root))
    except Exception as exc:
        logger.debug("workspace trust manifest: rule scan failed: %s", exc)
        return 0


def build_workspace_trust_manifest(
    raw_path: str,
    *,
    current_level: WorkspaceTrustLevel | None = None,
) -> WorkspaceTrustManifest:
    """Scan a workspace and build the FolderGate disclosure payload."""
    canonical = canonicalize_workspace_path(raw_path)
    repo_prefixes = load_repo_command_prefixes(canonical)
    config_path = Path(canonical) / ".myrm" / "config.toml"

    return WorkspaceTrustManifest(
        path=raw_path.strip(),
        canonical_path=canonical,
        skill_count=_count_workspace_skills(canonical),
        rule_count=_count_workspace_rules(canonical),
        repo_command_prefixes=repo_prefixes,
        has_myrm_config=config_path.is_file(),
        current_level=current_level,
    )


def manifest_hash(manifest: WorkspaceTrustManifest) -> str:
    """Stable hash for audit rows without storing full manifest bodies."""
    payload = {
        "canonical_path": manifest.canonical_path,
        "skill_count": manifest.skill_count,
        "rule_count": manifest.rule_count,
        "repo_command_prefixes": list(manifest.repo_command_prefixes),
        "has_myrm_config": manifest.has_myrm_config,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
