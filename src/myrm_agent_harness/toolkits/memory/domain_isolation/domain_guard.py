"""Domain isolation security guard enforcing recall boundaries and egress redlines.

[INPUT] Requested domains, active query context, target channels, and explicit user confirmation flags.
[OUTPUT] Validation verdicts and EgressDecision results guarding against cross-domain data leakage.
[POS] Harness framework toolkit memory guard layer for work/life domain integrity.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.domain_isolation.domain_registry import (
    DomainIsolationRegistry,
)
from myrm_agent_harness.toolkits.memory.domain_isolation.models import (
    DataDomain,
    EgressDecision,
)


class DomainIsolationGuard:
    """Enforces access controls, cross-domain recall rules, and outbound privacy redlines."""

    def __init__(self, registry: DomainIsolationRegistry) -> None:
        self._registry = registry

    def validate_write(self, domain: DataDomain) -> tuple[bool, str]:
        """Verify whether memory write is permitted for the target domain."""
        grant = self._registry.get_grant(domain)
        if not grant.allow_write:
            return False, f"域级权限门禁：{domain} 域的记忆写入功能已被用户关闭。"
        return True, "允许写入"

    def validate_recall(
        self,
        target_domain: DataDomain,
        active_domain: DataDomain,
        allow_cross_domain: bool = False,
    ) -> tuple[bool, str, bool]:
        """Verify whether memory recall from target_domain is permitted in active_domain context.

        Returns:
            (allowed: bool, reason: str, is_cross_domain: bool)
        """
        grant = self._registry.get_grant(target_domain)
        if not grant.allow_recall:
            return False, f"域级权限门禁：{target_domain} 域的记忆检索已被停用。", False

        if target_domain != active_domain:
            if not allow_cross_domain:
                return (
                    False,
                    (
                        f"跨域隔离拦截：当前活跃域为「{active_domain}」，"
                        f"默认禁止召回「{target_domain}」域记忆以防数据交叉污染。"
                    ),
                    True,
                )
            return True, f"允许跨域召回（来源: {target_domain}，当前: {active_domain}）", True

        return True, "同域召回放行", False

    def evaluate_egress(
        self,
        content_domain: DataDomain,
        target_channel: str,
        user_confirmed: bool = False,
    ) -> EgressDecision:
        """Evaluate egress redlines before sending messages or artifacts through external channels."""
        grant = self._registry.get_grant(content_domain)

        # Personal domain has strict egress redlines
        if content_domain == "personal":
            if not grant.allow_egress and not user_confirmed:
                return EgressDecision(
                    allowed=False,
                    requires_user_confirmation=True,
                    reason=(
                        f"隐私红线触发：检测到外发内容源自「生活/私人域（personal）」，"
                        f"目标渠道为「{target_channel}」。严禁静默外发，必须经用户显式确认。"
                    ),
                    source_domain="personal",
                    target_channel=target_channel,
                    is_cross_domain=True,
                )
            return EgressDecision(
                allowed=True,
                requires_user_confirmation=False,
                reason="生活域外发已通过用户显式授权或配置放行",
                source_domain="personal",
                target_channel=target_channel,
                is_cross_domain=True,
            )

        # Work domain follows grant settings
        if not grant.allow_egress and not user_confirmed:
            return EgressDecision(
                allowed=False,
                requires_user_confirmation=True,
                reason=f"外发策略限制：工作域对渠道「{target_channel}」的外发未授权，需用户确认。",
                source_domain="work",
                target_channel=target_channel,
                is_cross_domain=False,
            )

        return EgressDecision(
            allowed=True,
            requires_user_confirmation=False,
            reason="工作域外发合规放行",
            source_domain="work",
            target_channel=target_channel,
            is_cross_domain=False,
        )
