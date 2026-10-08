"""Single-point resolution and trust gating for remote memory configurations.

[INPUT]
- DirectoryTrustStore, target paths, project memory configuration.

[OUTPUT]
- ResolvedProjectRemote containing verified credentials or refusal notices.

[POS]
- Harness core security module enforcing fail-closed directory trust gating against remote egress.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.core.security.directory_trust_gate.trust_store import (
    DirectoryTrustStore,
)
from myrm_agent_harness.core.security.directory_trust_gate.types import (
    ProjectMemoryConfig,
    ResolvedProjectRemote,
    TrustDecision,
)

CONFIG_FILENAMES: tuple[str, ...] = (
    "myrm-memory.yaml",
    ".myrm-memory.yaml",
    ".plur.yaml",
)


class RemoteMemoryTrustGate:
    """Atomic, single-point resolver preventing TOCTOU and untrusted remote memory egress."""

    @staticmethod
    def format_refusal_notice(refused_from_dir: str) -> str:
        """Standardized actionable security notice when remote memory settings are dropped."""
        return (
            f"[MYRM_SECURITY] Ignored remote memory settings in project configuration — "
            f"'{refused_from_dir}' is not a trusted directory, and those settings would send "
            f"prompt text to the remote host they name. If this project is yours, run: "
            f"myrm trust '{refused_from_dir}'"
        )

    @classmethod
    def resolve_from_config(
        cls,
        trust_store: DirectoryTrustStore,
        config: ProjectMemoryConfig,
        config_path: str | Path | None,
    ) -> ResolvedProjectRemote:
        """Single-point evaluation of in-memory or already-read project memory config."""
        if config_path is None:
            config_dir_str: str | None = None
            is_trusted = False
        else:
            resolved_file = Path(config_path).resolve()
            config_dir_str = str(resolved_file.parent)
            is_trusted = trust_store.is_directory_trusted(resolved_file.parent)

        has_remote = bool(config.remote_url and config.remote_token)

        if not has_remote:
            has_scope = bool(config.scope or config.domain)
            return ResolvedProjectRemote(
                config_path=str(config_path) if config_path else None,
                config_dir=config_dir_str,
                is_directory_trusted=is_trusted,
                effective_scope=config.scope,
                effective_domain=config.domain,
                remote_url=None,
                remote_token=None,
                remote_scopes=[],
                refusal_notice=None,
                decision=(
                    TrustDecision.LOCAL_SCOPE_ONLY
                    if has_scope
                    else TrustDecision.NO_CONFIG_FOUND
                ),
            )

        # Config has remote memory destination
        if is_trusted:
            return ResolvedProjectRemote(
                config_path=str(config_path) if config_path else None,
                config_dir=config_dir_str,
                is_directory_trusted=True,
                effective_scope=config.scope,
                effective_domain=config.domain,
                remote_url=config.remote_url,
                remote_token=config.remote_token,
                remote_scopes=list(config.remote_scopes),
                refusal_notice=None,
                decision=TrustDecision.TRUSTED_AUTHORIZED,
            )

        # Fail-closed: untrusted directory attempting remote memory egress
        refusal_dir = config_dir_str or "(unknown directory)"
        return ResolvedProjectRemote(
            config_path=str(config_path) if config_path else None,
            config_dir=config_dir_str,
            is_directory_trusted=False,
            effective_scope=config.scope,
            effective_domain=config.domain,
            remote_url=None,
            remote_token=None,
            remote_scopes=[],
            refusal_notice=cls.format_refusal_notice(refusal_dir),
            decision=TrustDecision.UNTRUSTED_REMOTE_REFUSED,
        )

    @classmethod
    def resolve_from_directory(
        cls,
        trust_store: DirectoryTrustStore,
        start_dir: str | Path,
        config: ProjectMemoryConfig | None = None,
    ) -> ResolvedProjectRemote:
        """Resolve memory configuration from start directory, locating config atomically."""
        curr = Path(start_dir).resolve()

        # If explicit config provided, use start_dir as config directory
        if config is not None:
            dummy_path = curr / "myrm-memory.yaml"
            return cls.resolve_from_config(trust_store, config, dummy_path)

        # Walk upward to find memory config file
        search_dirs = [curr, *curr.parents]
        found_file: Path | None = None

        for directory in search_dirs:
            for candidate in CONFIG_FILENAMES:
                target = directory / candidate
                if target.is_file():
                    found_file = target
                    break
            if found_file is not None:
                break

        if found_file is None:
            return ResolvedProjectRemote(
                config_path=None,
                config_dir=None,
                is_directory_trusted=trust_store.is_directory_trusted(curr),
                effective_scope=None,
                effective_domain=None,
                remote_url=None,
                remote_token=None,
                remote_scopes=[],
                refusal_notice=None,
                decision=TrustDecision.NO_CONFIG_FOUND,
            )

        # Found config file, evaluate with empty default if not read from disk
        return cls.resolve_from_config(
            trust_store,
            ProjectMemoryConfig(),
            found_file,
        )
