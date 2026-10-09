"""Engine generating Sandbox Trust Badges and Permission Boundary Cards."""

from __future__ import annotations

import uuid

from .health_probe import SandboxHealthSelfAuditProbe
from .types import (
    IsolationLevel,
    PermissionBoundaryCard,
    SandboxHealthAuditReport,
    SandboxTrustBadge,
    TrustGrade,
)

_STANDARD_DENIED_PATHS: list[str] = [
    "/etc/shadow",
    "/root",
    "~/.ssh",
    "~/.aws",
    "/var/run/docker.sock",
    "*vault*.db",
]

_DEFAULT_ACTIVE_GUARDS: list[str] = [
    "PreFlightIrreversibleWriteGuard",
    "SensitiveVaultAndCredentialFileOverwriteDenyGuard",
    "SentinelOutboundTrafficReviewer",
    "CompoundShellRiskInterceptor",
    "UntrustedProjectConfigIsolationGate",
]


class SandboxTrustAuditCardEngine:
    """Produces user-visible trust badges, boundary inspection cards, and orchestrates health audits."""

    def __init__(
        self,
        probe: SandboxHealthSelfAuditProbe | None = None,
    ) -> None:
        self._probe = probe or SandboxHealthSelfAuditProbe()

    @property
    def probe(self) -> SandboxHealthSelfAuditProbe:
        """Access health diagnostic probe."""
        return self._probe

    def run_environment_audit(
        self,
        environment_id: str,
        isolation_level: IsolationLevel,
        mounted_paths: list[str] | None = None,
        env_vars: dict[str, str] | None = None,
        is_root: bool = False,
        egress_monitored: bool = True,
    ) -> SandboxHealthAuditReport:
        """Run self-audit probe against target environment."""
        return self._probe.run_audit(
            environment_id=environment_id,
            isolation_level=isolation_level,
            mounted_paths=mounted_paths,
            env_vars=env_vars,
            is_root=is_root,
            egress_monitored=egress_monitored,
        )

    def generate_badge(
        self,
        isolation_level: IsolationLevel,
        audit_score: int = 100,
    ) -> SandboxTrustBadge:
        """Calculate dynamic trust badge presented in UI headers and status bars."""
        if isolation_level == IsolationLevel.CLOUD_DEDICATED_SANDBOX:
            if audit_score >= 85:
                grade = TrustGrade.MAXIMUM_ISOLATION
                label = "云托管专属沙箱 (硬件容器+独立Volume物理隔离)"
                summary = "硬件级容器隔离，挂载独立持久化 Volume，出站全量 Sentinel 看门狗审查"
                color = "#10B981"  # Emerald green
            else:
                grade = TrustGrade.HIGH_ISOLATION
                label = "云托管沙箱 (部分配置警告)"
                summary = "容器环境已隔离，但发现部分敏感环境变量或网络警告"
                color = "#3B82F6"  # Blue

        elif isolation_level == IsolationLevel.LOCAL_RESTRICTED_CONTAINER:
            grade = TrustGrade.RESTRICTED_SANDBOXED
            label = "本地受限沙箱 (容器只读挂载隔离)"
            summary = "本地 Docker/Container 隔离环境，宿主敏感路径写保护生效"
            color = "#6366F1"  # Indigo

        else:
            grade = TrustGrade.UNCONFINED_HOST
            label = "全权限宿主执行态 (需严格二次确认)"
            summary = "直接在宿主系统运行，无硬件容器边界，高危操作强制事前拦截"
            color = "#F59E0B"  # Amber

        return SandboxTrustBadge(
            isolation_level=isolation_level,
            trust_grade=grade,
            trust_score=audit_score,
            summary=summary,
            badge_label=label,
            color_hex=color,
        )

    def generate_boundary_card(
        self,
        environment_id: str,
        isolation_level: IsolationLevel,
        allowed_paths: list[str] | None = None,
        active_guards: list[str] | None = None,
    ) -> PermissionBoundaryCard:
        """Construct interactive permission boundary card detailing active path and network boundaries."""
        resolved_allowed = allowed_paths or [
            "/workspace",
            "/tmp/sandbox",
            f"/mnt/volumes/{environment_id}/data",
        ]
        resolved_guards = active_guards or list(_DEFAULT_ACTIVE_GUARDS)
        card_id = f"bnd_card_{uuid.uuid4().hex[:12]}"

        egress_policy = (
            "Sentinel Pre-Outbound Reviewer Active (Strict Zero-Leakage & Exfiltration Deny)"
            if isolation_level != IsolationLevel.HOST_DIRECT_FULL_TRUST
            else "Host Egress Direct (Subject to local interceptor hooks)"
        )

        return PermissionBoundaryCard(
            card_id=card_id,
            environment_id=environment_id,
            isolation_level=isolation_level,
            allowed_paths=resolved_allowed,
            denied_paths=list(_STANDARD_DENIED_PATHS),
            egress_policy=egress_policy,
            active_guards=resolved_guards,
        )
