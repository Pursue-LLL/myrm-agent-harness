"""Autonomous opportunity sensing engine scanning workspace and state signals.

[INPUT]
- proactive_kernel_types::HeartbeatChecklistItem, HeartbeatManifest, OpportunityCategory, ProactiveOpportunity (POS: Domain models)

[OUTPUT]
- OpportunitySensingEngine: Discovers proactive assistance opportunities from environment snapshots.

[POS]
Background inspection engine inspired by OpenClaw/Muse/Instinct, actively evaluating
workspace signals (git drift, upcoming schedules, stale todos, security hygiene).
"""

from __future__ import annotations

import uuid
from typing import Mapping, Sequence

from .proactive_kernel_types import (
    HeartbeatChecklistItem,
    HeartbeatManifest,
    OpportunityCategory,
    ProactiveOpportunity,
)


class OpportunitySensingEngine:
    """Evaluates environmental state snapshots against manifest checklist items."""

    @classmethod
    def scan_opportunities(
        cls,
        manifest: HeartbeatManifest,
        environment_signals: Mapping[str, object] | None = None,
    ) -> list[ProactiveOpportunity]:
        """Scan environment state and identify high-value proactive opportunities."""
        signals = environment_signals or {}
        discovered: list[ProactiveOpportunity] = []

        for item in manifest.checklist_items:
            if not item.is_active:
                continue

            opps = cls._evaluate_checklist_item(item, signals)
            discovered.extend(opps)

        return discovered

    @classmethod
    def _evaluate_checklist_item(
        cls,
        item: HeartbeatChecklistItem,
        signals: Mapping[str, object],
    ) -> list[ProactiveOpportunity]:
        opps: list[ProactiveOpportunity] = []
        cat = item.target_category

        if cat == OpportunityCategory.WORKSPACE_DRIFT:
            # Check for uncommitted diffs or failing tests
            failing_tests = bool(signals.get("has_failing_tests", False))
            dirty_files_count = int(signals.get("uncommitted_files_count", 0))
            if failing_tests:
                opps.append(
                    ProactiveOpportunity(
                        opportunity_id=f"opp-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        title="检测到单元测试回归失败",
                        detail=str(signals.get("failing_test_summary", "本地工作区存在未通过测试用例")),
                        confidence_score=0.95,
                        urgency_score=0.90,
                        suggested_action="自动定位并修复报错用例",
                        action_payload="run_test_fix",
                    )
                )
            elif dirty_files_count >= 10:
                opps.append(
                    ProactiveOpportunity(
                        opportunity_id=f"opp-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        title=f"工作区存在 {dirty_files_count} 个未暂存改动",
                        detail="长期未提交代码存在冲突与意外丢失风险，建议生成保护性提交快照。",
                        confidence_score=0.80,
                        urgency_score=0.60,
                        suggested_action="一键生成结构化 Git 提交",
                        action_payload="git_commit_proposal",
                    )
                )

        elif cat == OpportunityCategory.SCHEDULE_ALERT:
            # Check for upcoming calendar meetings
            minutes_to_meeting = signals.get("minutes_to_next_meeting")
            if isinstance(minutes_to_meeting, (int, float)) and minutes_to_meeting <= 30:
                meeting_title = str(signals.get("next_meeting_title", "日程会议"))
                opps.append(
                    ProactiveOpportunity(
                        opportunity_id=f"opp-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        title=f"会议即将在 {int(minutes_to_meeting)} 分钟后开始: {meeting_title}",
                        detail="检测到日程冲突或会议备忘材料待整理，已准备好简报。",
                        confidence_score=0.92,
                        urgency_score=0.95 if minutes_to_meeting <= 15 else 0.70,
                        suggested_action="展开会议背景简报与议程要点",
                        action_payload="view_meeting_brief",
                    )
                )

        elif cat == OpportunityCategory.TODO_REMINDER:
            # Check for open unresolved actions
            pending_todos = signals.get("pending_todo_items")
            if isinstance(pending_todos, Sequence) and len(pending_todos) > 0:
                first_todo = str(pending_todos[0])
                opps.append(
                    ProactiveOpportunity(
                        opportunity_id=f"opp-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        title=f"遗留待办跟进: {first_todo[:40]}...",
                        detail=f"前序会话标记了 {len(pending_todos)} 个未完结待办，建议确认是否继续推进。",
                        confidence_score=0.85,
                        urgency_score=0.50,
                        suggested_action="恢复先前未完成目标",
                        action_payload="resume_todo_pipeline",
                    )
                )

        elif cat == OpportunityCategory.SECURITY_HYGIENE:
            # Check for credential leakage or stale secrets
            leaked_secrets = bool(signals.get("detected_plaintext_secrets", False))
            if leaked_secrets:
                opps.append(
                    ProactiveOpportunity(
                        opportunity_id=f"opp-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        title="工作区疑似包含明文敏感凭据",
                        detail="静态扫描探测到环境变量或配置中包含未脱敏的 API 密钥。",
                        confidence_score=0.98,
                        urgency_score=0.99,
                        suggested_action="执行敏感凭据隔离与沙箱环境变量脱敏",
                        action_payload="sanitize_secrets",
                    )
                )

        elif cat == OpportunityCategory.OPTIMIZATION_PROPOSAL:
            # Optimization suggestions
            has_dead_code = bool(signals.get("detected_dead_code", False))
            if has_dead_code:
                opps.append(
                    ProactiveOpportunity(
                        opportunity_id=f"opp-{uuid.uuid4().hex[:8]}",
                        category=cat,
                        title="发现可优化的冗余代码与废弃依赖",
                        detail="代码库中存在超过 3 个未引用的临时模块，清理可提升构建速度。",
                        confidence_score=0.75,
                        urgency_score=0.35,
                        suggested_action="生成纯净重构清理方案",
                        action_payload="clean_dead_code",
                    )
                )

        return opps
