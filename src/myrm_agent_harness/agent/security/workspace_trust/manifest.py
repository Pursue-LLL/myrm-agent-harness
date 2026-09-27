"""Build pre-bind workspace trust manifests for FolderGate disclosure.

[INPUT]
- hashlib::hashlib (POS: Python 内容哈希标准库)
- json::json (POS: Python JSON 序列化标准库)
- logging::logging (POS: Python 标准日志库)
- os::os (POS: Python 路径与文件系统标准库)
- pathlib::Path (POS: Python 面向对象路径标准库)
- agent.security.workspace_trust.repo_policy::load_repo_command_prefixes
  (POS: 仓库声明命令前缀读取层)
- agent.security.workspace_trust.types::WorkspaceTrustLevel, WorkspaceTrustManifest
  (POS: 工作区信任级别与披露载荷类型)

[OUTPUT]
- canonicalize_workspace_path: resolved absolute path, or "" for blank input
- build_workspace_trust_manifest: disclosure payload with skill/rule counts and prefixes
- manifest_hash: stable hash identifying the disclosed payload

[POS]
Disclosure layer of the workspace_trust gate: it tells the user what a folder would gain
before trust is granted. Skill and rule scans are advisory and fail open to zero counts so
a broken scanner can never block the trust prompt; the hash changes when scope changes.
"""

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


def _count_workspace_mcps(workspace_root: str) -> int:
    try:
        count = 0
        root = Path(workspace_root)
        candidate_paths = [
            root / "mcp.json",
            root / ".myrm" / "mcp.json",
            root / ".cursor" / "mcp.json",
            root / ".vscode" / "mcp.json",
        ]
        for cfg in candidate_paths:
            if cfg.is_file():
                try:
                    data = json.loads(cfg.read_text(encoding="utf-8"))
                    servers = data.get("mcpServers", {})
                    if isinstance(servers, dict) and servers:
                        count += len(servers)
                    else:
                        count += 1
                except Exception:
                    count += 1
        return count
    except Exception as exc:
        logger.debug("workspace trust manifest: mcp scan failed: %s", exc)
        return 0


def _count_workspace_plugins(workspace_root: str) -> int:
    try:
        count = 0
        root = Path(workspace_root)
        myrm_plugins = root / ".myrm" / "plugins"
        if myrm_plugins.is_dir():
            for item in myrm_plugins.iterdir():
                if (item.is_dir() and (item / "plugin.json").is_file()) or (item.is_file() and item.suffix == ".zip"):
                    count += 1
        if (root / "plugin.json").is_file():
            count += 1
        return count
    except Exception as exc:
        logger.debug("workspace trust manifest: plugin scan failed: %s", exc)
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
        mcp_count=_count_workspace_mcps(canonical),
        plugin_count=_count_workspace_plugins(canonical),
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
        "mcp_count": manifest.mcp_count,
        "plugin_count": manifest.plugin_count,
        "repo_command_prefixes": list(manifest.repo_command_prefixes),
        "has_myrm_config": manifest.has_myrm_config,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
