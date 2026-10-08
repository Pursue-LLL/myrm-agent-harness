"""Single-point atomic resolver for project memory configurations with directory trust gating.

[INPUT]
- ProjectMemoryConfig, optional config path, and DirectoryTrustStore.

[OUTPUT]
- ResolvedProjectRemote separating local scope filtering from authorized remote memory egress.

[POS]
- Harness core security module preventing TOCTOU races and unauthorized remote memory exfiltration.
"""

from __future__ import annotations

import os

from myrm_agent_harness.core.security.directory_trust_remote_memory.trust_store import (
    DirectoryTrustStore,
)
from myrm_agent_harness.core.security.directory_trust_remote_memory.types import (
    ProjectMemoryConfig,
    RemoteMemoryConfig,
    ResolvedProjectRemote,
    TrustStatus,
)


def build_remote_refusal_notice(refused_from: str) -> str:
    """Format standardized user notice when remote memory settings are blocked by untrusted directory."""
    return (
        f"[MYRM] Ignored remote memory settings in project config — "
        f"{refused_from} is not a trusted directory, and those settings would "
        f"send prompt/memory text to the host they name. "
        f"To authorize this project, run: myrm trust {refused_from}"
    )


class SinglePointRemoteMemoryResolver:
    """Performs atomic single-point resolution of project memory configs against directory trust gates."""

    @staticmethod
    def resolve_from_config(
        config: ProjectMemoryConfig,
        config_path: str | None,
        trust_store: DirectoryTrustStore,
    ) -> ResolvedProjectRemote:
        """Resolve project memory settings atomically, preventing TOCTOU race conditions."""
        config_dir: str | None = None
        if config_path:
            try:
                expanded = os.path.expanduser(config_path)
                canonical_path = os.path.realpath(os.path.abspath(expanded))
                config_dir = os.path.dirname(canonical_path)
            except Exception:
                config_dir = None

        has_remote_declaration = bool(config.remote_url and config.remote_token)

        # 1. If project has no remote destination declared, local scoping is accepted without remote egress
        if not has_remote_declaration:
            return ResolvedProjectRemote(
                config_path=config_path,
                config_dir=config_dir,
                trust_status=TrustStatus.TRUSTED
                if (config_dir and trust_store.is_directory_trusted(config_dir))
                else TrustStatus.UNTRUSTED,
                is_trusted=bool(
                    config_dir and trust_store.is_directory_trusted(config_dir)
                ),
                remote_memory=None,
                refused_from=None,
                refusal_notice=None,
                effective_scope=config.local_scope,
                is_outbound_authorized=False,
            )

        # 2. Project declares remote URL and token: check directory trust
        is_trusted = False
        trust_status = TrustStatus.UNTRUSTED
        try:
            if config_dir is not None and trust_store.is_directory_trusted(
                config_dir
            ):
                is_trusted = True
                trust_status = TrustStatus.TRUSTED
        except Exception:
            is_trusted = False
            trust_status = TrustStatus.ERROR_FAIL_CLOSED

        if not is_trusted:
            refused_loc = config_dir if config_dir is not None else "(unknown directory)"
            return ResolvedProjectRemote(
                config_path=config_path,
                config_dir=config_dir,
                trust_status=trust_status,
                is_trusted=False,
                remote_memory=None,
                refused_from=refused_loc,
                refusal_notice=build_remote_refusal_notice(refused_loc),
                effective_scope=config.local_scope,
                is_outbound_authorized=False,
            )

        # 3. Directory is trusted: authorize remote memory config
        assert config.remote_url is not None
        assert config.remote_token is not None
        remote_cfg = RemoteMemoryConfig(
            url=config.remote_url,
            token=config.remote_token,
            scopes=list(config.remote_scopes),
        )

        return ResolvedProjectRemote(
            config_path=config_path,
            config_dir=config_dir,
            trust_status=TrustStatus.TRUSTED,
            is_trusted=True,
            remote_memory=remote_cfg,
            refused_from=None,
            refusal_notice=None,
            effective_scope=config.local_scope,
            is_outbound_authorized=True,
        )
