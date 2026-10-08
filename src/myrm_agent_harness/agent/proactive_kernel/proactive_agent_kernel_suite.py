"""Unified facade suite for proactive agent micro-kernel, heartbeat loops, and low-friction contract.

[INPUT]
- proactive_kernel_types::* (POS: Domain data models)
- heartbeat_manifest_parser::HeartbeatManifestParser (POS: Manifest parser)
- opportunity_sensing_engine::OpportunitySensingEngine (POS: Opportunity sensing engine)
- zero_nag_discretion_gate::ZeroNagDiscretionGate (POS: Zero-nag discretion gate)

[OUTPUT]
- ProactiveAgentKernelSuite: High-level facade for autonomous heartbeat execution and opportunity delivery.

[POS]
Entry point coordinating OpenClaw-inspired Markdown manifest parsing, autonomous
opportunity sensing, and zero-nag etiquette delivery channels.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Mapping, Sequence
import uuid

from .heartbeat_manifest_parser import HeartbeatManifestParser
from .opportunity_sensing_engine import OpportunitySensingEngine
from .proactive_kernel_types import (
    HeartbeatManifest,
    ProactiveHeartbeatResult,
    ProactiveOpportunity,
    ProactivityDiscretionTier,
)
from .zero_nag_discretion_gate import ZeroNagDiscretionGate


class ProactiveAgentKernelSuite:
    """Industrial-grade proactive agent micro-kernel facade coordinating autonomous loops."""

    @classmethod
    def load_manifest(
        cls,
        workspace_path_or_content: str | Path | None = None,
    ) -> HeartbeatManifest:
        """Load and parse HEARTBEAT.md manifest from a workspace path or raw string."""
        if workspace_path_or_content is None:
            return HeartbeatManifestParser.build_default_manifest()

        if isinstance(workspace_path_or_content, Path) or (
            isinstance(workspace_path_or_content, str) and "\n" not in workspace_path_or_content
        ):
            target_path = Path(workspace_path_or_content)
            if target_path.is_dir():
                target_path = target_path / "HEARTBEAT.md"

            if target_path.exists() and target_path.is_file():
                try:
                    content = target_path.read_text(encoding="utf-8")
                    return HeartbeatManifestParser.parse_manifest(content)
                except Exception:
                    pass
            return HeartbeatManifestParser.build_default_manifest()

        # Direct markdown content string
        return HeartbeatManifestParser.parse_manifest(str(workspace_path_or_content))

    @classmethod
    def execute_heartbeat_tick(
        cls,
        manifest: HeartbeatManifest | None = None,
        *,
        environment_signals: Mapping[str, object] | None = None,
        gate: ZeroNagDiscretionGate | None = None,
    ) -> ProactiveHeartbeatResult:
        """Execute one autonomous heartbeat tick: sense, adjudicate, and categorize opportunities."""
        man = manifest or HeartbeatManifestParser.build_default_manifest()
        effective_gate = gate or ZeroNagDiscretionGate()

        # 1. Opportunity sensing
        raw_opportunities = OpportunitySensingEngine.scan_opportunities(
            manifest=man,
            environment_signals=environment_signals,
        )

        # 2. Zero-nag adjudication
        adjudicated = effective_gate.adjudicate_opportunities(
            opportunities=raw_opportunities,
            manifest=man,
        )

        # 3. Channel classification
        urgent_list: list[ProactiveOpportunity] = []
        docked_list: list[ProactiveOpportunity] = []
        memo_list: list[ProactiveOpportunity] = []
        suppressed_count = 0

        for opp in adjudicated:
            if opp.discretion_tier == ProactivityDiscretionTier.CRITICAL_URGENT:
                urgent_list.append(opp)
            elif opp.discretion_tier == ProactivityDiscretionTier.OPPORTUNITY_DOCK:
                docked_list.append(opp)
            elif opp.discretion_tier == ProactivityDiscretionTier.SILENT_MEMORY_MEMO:
                memo_list.append(opp)
            else:
                suppressed_count += 1

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        heartbeat_id = f"hb-{uuid.uuid4().hex[:8]}"

        summary = (
            f"Heartbeat tick completed. Discovered {len(raw_opportunities)} opportunities: "
            f"{len(urgent_list)} urgent, {len(docked_list)} docked, {len(memo_list)} memoized, "
            f"{suppressed_count} noise/throttled."
        )

        return ProactiveHeartbeatResult(
            heartbeat_id=heartbeat_id,
            timestamp_utc=now_utc,
            opportunities_discovered=len(raw_opportunities),
            surfaced_urgent=tuple(urgent_list),
            docked_opportunities=tuple(docked_list),
            memoized_opportunities=tuple(memo_list),
            suppressed_count=suppressed_count,
            is_rate_limited=False,
            status_summary=summary,
        )

    @classmethod
    def format_opportunity_dock_markdown(
        cls,
        docked_opportunities: Sequence[ProactiveOpportunity],
    ) -> str:
        """Render docked opportunities into a clean Markdown bubble for chat footers."""
        if not docked_opportunities:
            return ""

        lines = [
            "💡 **主动机会停靠坞 (Opportunity Dock)**",
            "> 以下为智能体在后台自主感知到的协作建议，点击即可采纳或忽略：",
        ]
        for opp in docked_opportunities:
            lines.append(
                f"- **{opp.title}** ({int(opp.confidence_score * 100)}% 置信度): "
                f"{opp.detail} → `[建议动作: {opp.suggested_action}]`"
            )

        return "\n".join(lines) + "\n"

    @classmethod
    def format_memory_memo_entry(
        cls,
        memoized_opportunities: Sequence[ProactiveOpportunity],
    ) -> str:
        """Format silent opportunities for background append into MEMORY.md."""
        if not memoized_opportunities:
            return ""

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [f"## [Heartbeat Memo - {now_str}]"]
        for opp in memoized_opportunities:
            lines.append(f"- **{opp.category.value}**: {opp.title} ({opp.detail})")

        return "\n".join(lines) + "\n"


# Alias for roadmap specification fidelity
ProactiveAgentKernelContractAndInstinctiveProactivityLoopSuite = ProactiveAgentKernelSuite
