"""Static inspector for 4D action surfaces (Tools, Files, APIs, Sends) and 8 atomic action categories."""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.blast_radius_inspector.types import (
    ActionSurfaceDimension,
    ActionSurfaceExposureReport,
    AtomicActionCategory,
    DangerTier,
    SinkVulnerabilityItem,
)

logger = logging.getLogger(__name__)

# Heuristic mapping from tool/action name keywords to atomic action categories & dimensions
_ACTION_MAPPING: dict[str, tuple[AtomicActionCategory, ActionSurfaceDimension]] = {
    "browse": (AtomicActionCategory.BROWSE, ActionSurfaceDimension.TOOLS),
    "navigate": (AtomicActionCategory.BROWSE, ActionSurfaceDimension.TOOLS),
    "scrape": (AtomicActionCategory.BROWSE, ActionSurfaceDimension.TOOLS),
    "email": (AtomicActionCategory.EMAIL, ActionSurfaceDimension.SENDS),
    "send_mail": (AtomicActionCategory.EMAIL, ActionSurfaceDimension.SENDS),
    "post": (AtomicActionCategory.POST, ActionSurfaceDimension.SENDS),
    "tweet": (AtomicActionCategory.POST, ActionSurfaceDimension.SENDS),
    "publish": (AtomicActionCategory.POST, ActionSurfaceDimension.SENDS),
    "schedule": (AtomicActionCategory.SCHEDULE, ActionSurfaceDimension.TOOLS),
    "cron": (AtomicActionCategory.SCHEDULE, ActionSurfaceDimension.TOOLS),
    "approve": (AtomicActionCategory.APPROVE, ActionSurfaceDimension.TOOLS),
    "grant": (AtomicActionCategory.APPROVE, ActionSurfaceDimension.TOOLS),
    "write_file": (AtomicActionCategory.WRITE_FILE, ActionSurfaceDimension.FILES),
    "edit_file": (AtomicActionCategory.WRITE_FILE, ActionSurfaceDimension.FILES),
    "save_file": (AtomicActionCategory.WRITE_FILE, ActionSurfaceDimension.FILES),
    "delete_file": (AtomicActionCategory.WRITE_FILE, ActionSurfaceDimension.FILES),
    "http_request": (AtomicActionCategory.TRIGGER_API, ActionSurfaceDimension.APIS),
    "curl": (AtomicActionCategory.TRIGGER_API, ActionSurfaceDimension.APIS),
    "webhook": (AtomicActionCategory.TRIGGER_API, ActionSurfaceDimension.APIS),
    "shell_exec": (AtomicActionCategory.MUTATE_SYSTEM, ActionSurfaceDimension.TOOLS),
    "bash": (AtomicActionCategory.MUTATE_SYSTEM, ActionSurfaceDimension.TOOLS),
    "run_command": (AtomicActionCategory.MUTATE_SYSTEM, ActionSurfaceDimension.TOOLS),
}


class ActionSurfaceStaticInspector:
    """Zero-LLM pure static inspector evaluating agent action surface blast radius and pre-admission."""

    def __init__(self, critical_exposure_threshold: float = 75.0) -> None:
        self._critical_exposure_threshold = critical_exposure_threshold

    def inspect_profile(
        self,
        tools: list[str],
        declared_file_scopes: list[str],
        declared_api_endpoints: list[str],
        declared_send_channels: list[str],
        installed_plugins: list[str] | None = None,
    ) -> tuple[ActionSurfaceExposureReport, list[SinkVulnerabilityItem]]:
        """Inspect agent configuration across 4 dimensions and 8 atomic action categories.

        Returns:
            Tuple of (ActionSurfaceExposureReport, list of detected SinkVulnerabilityItems).
        """
        plugins = installed_plugins or []
        sinks: list[SinkVulnerabilityItem] = []
        action_counts: dict[str, int] = {cat.value: 0 for cat in AtomicActionCategory}

        # 1. Analyze Tools
        for tool_name in tools:
            matched = False
            tool_lower = tool_name.lower()
            for kw, (cat, dim) in _ACTION_MAPPING.items():
                if kw in tool_lower:
                    action_counts[cat.value] += 1
                    sinks.append(
                        SinkVulnerabilityItem(
                            action_category=cat,
                            dimension=dim,
                            sink_identifier=tool_name,
                            danger_tier=DangerTier.REACHABLE_VERIFIED,
                            description=f"Directly configured active tool: {tool_name}",
                        )
                    )
                    matched = True
                    break
            if not matched:
                action_counts[AtomicActionCategory.TRIGGER_API.value] += 1

        # 2. Analyze File Scopes
        for scope in declared_file_scopes:
            action_counts[AtomicActionCategory.WRITE_FILE.value] += 1
            sinks.append(
                SinkVulnerabilityItem(
                    action_category=AtomicActionCategory.WRITE_FILE,
                    dimension=ActionSurfaceDimension.FILES,
                    sink_identifier=f"file_scope:{scope}",
                    danger_tier=DangerTier.REACHABLE_VERIFIED,
                    description=f"Filesystem access scope: {scope}",
                )
            )

        # 3. Analyze External APIs
        for endpoint in declared_api_endpoints:
            action_counts[AtomicActionCategory.TRIGGER_API.value] += 1
            sinks.append(
                SinkVulnerabilityItem(
                    action_category=AtomicActionCategory.TRIGGER_API,
                    dimension=ActionSurfaceDimension.APIS,
                    sink_identifier=f"api:{endpoint}",
                    danger_tier=DangerTier.REACHABLE_VERIFIED,
                    description=f"Declared external API endpoint: {endpoint}",
                )
            )

        # 4. Analyze Send Channels
        for ch in declared_send_channels:
            cat = AtomicActionCategory.EMAIL if "mail" in ch.lower() else AtomicActionCategory.POST
            action_counts[cat.value] += 1
            sinks.append(
                SinkVulnerabilityItem(
                    action_category=cat,
                    dimension=ActionSurfaceDimension.SENDS,
                    sink_identifier=f"send_channel:{ch}",
                    danger_tier=DangerTier.REACHABLE_VERIFIED,
                    description=f"Unbounded external communication channel: {ch}",
                )
            )

        # 5. Analyze Installed Plugins (Install-liability: dormant until activated)
        for plugin in plugins:
            sinks.append(
                SinkVulnerabilityItem(
                    action_category=AtomicActionCategory.MUTATE_SYSTEM,
                    dimension=ActionSurfaceDimension.TOOLS,
                    sink_identifier=f"plugin_liability:{plugin}",
                    danger_tier=DangerTier.INSTALL_LIABILITY,
                    description=f"Installed third-party plugin liability: {plugin}",
                )
            )

        reachable_count = sum(1 for s in sinks if s.danger_tier == DangerTier.REACHABLE_VERIFIED)
        liability_count = sum(1 for s in sinks if s.danger_tier == DangerTier.INSTALL_LIABILITY)

        # Calculate normalized exposure score (0 - 100)
        tools_weight = len(tools) * 5.0
        files_weight = len(declared_file_scopes) * 10.0
        apis_weight = len(declared_api_endpoints) * 8.0
        sends_weight = len(declared_send_channels) * 15.0
        liability_weight = len(plugins) * 4.0

        raw_score = tools_weight + files_weight + apis_weight + sends_weight + liability_weight
        exposure_score = min(round(raw_score, 1), 100.0)

        pre_admission_allowed = exposure_score <= self._critical_exposure_threshold
        rejection_reason = (
            f"Pre-admission rejected: Exposure blast radius score {exposure_score} exceeds "
            f"threshold {self._critical_exposure_threshold}. Unbounded sends or critical file scopes detected."
            if not pre_admission_allowed
            else None
        )

        report = ActionSurfaceExposureReport(
            total_tools_count=len(tools),
            total_files_scope_count=len(declared_file_scopes),
            total_apis_count=len(declared_api_endpoints),
            total_sends_count=len(declared_send_channels),
            action_breakdown=action_counts,
            reachable_verified_count=reachable_count,
            install_liability_count=liability_count,
            unguarded_critical_count=reachable_count,  # Before guard attribution
            exposure_score=exposure_score,
            pre_admission_allowed=pre_admission_allowed,
            admission_rejection_reason=rejection_reason,
        )

        return (report, sinks)
