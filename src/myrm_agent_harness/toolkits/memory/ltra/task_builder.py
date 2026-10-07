"""Followup task blueprint builder for LTRA cognitive pipeline.

[POS]
随身感知“办”执行工单草稿生成器。将确认的事实四元组自动转换为结构化沙箱
执行任务草稿，规划工作区交付产物路径与行动步骤，内置派发幂等令牌。

[INPUT]
- CognitiveFactQuadruple 事实对象
- 目标智能体角色偏好

[OUTPUT]
- FollowupTaskDraftBuilder: 沙箱任务派发草稿生成引擎
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime

from .models import CognitiveFactQuadruple, FollowupTaskDraft


class FollowupTaskDraftBuilder:
    """Constructs actionable sandbox task specifications from distilled cognitive facts."""

    @classmethod
    def build_draft(
        cls,
        fact: CognitiveFactQuadruple,
        target_agent_role: str = "方案架构专家",
    ) -> FollowupTaskDraft:
        """Create structured task specification ready for sandbox worker execution."""
        task_id = f"task_ltra_{uuid.uuid4().hex[:12]}"
        date_prefix = datetime.now(UTC).strftime("%Y%m%d")

        # Clean demand keyword for safe file path
        slug_keyword = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", fact.demand)[:24].strip("_")
        if not slug_keyword:
            slug_keyword = "requirement_brief"

        deliverable_path = f"workspace/followups/{date_prefix}_{slug_keyword}.md"

        # Evidence quote compilation
        evidence_quotes = [
            f"[{a.start_ms}ms-{a.end_ms}ms] \"{a.verbatim_quote}\""
            for a in fact.anchors
        ]
        verbatim_evidence = "\n".join(evidence_quotes) if evidence_quotes else "来自会议口头诉求记录"

        title = f"【随身外设感知派办】落实 {fact.subject} 的诉求：{fact.demand[:30]}"
        objective = (
            f"根据现场录音事实，针对 {fact.subject} 提出的 '{fact.demand}'，"
            f"落实我方承诺 '{fact.commitment}' 并排查卡点 '{fact.pending_issue}'。"
        )
        context_summary = fact.to_concise_summary()

        action_plan_steps = (
            f"1. 深入分析 {fact.subject} 核心诉求与现场上下文约束",
            f"2. 针对承诺 '{fact.commitment}' 设计具体实现架构或执行步骤",
            f"3. 排查卡点 '{fact.pending_issue}' 并制定可行解法",
            f"4. 在 {deliverable_path} 输出正式方案纪要并交付用户审阅",
        )

        # Idempotency token based on fact id and agent role
        idempotency_seed = f"{fact.fact_id}:{target_agent_role}".encode()
        idempotency_token = hashlib.sha256(idempotency_seed).hexdigest()[:20]

        return FollowupTaskDraft(
            task_id=task_id,
            source_fact_id=fact.fact_id,
            title=title,
            objective=objective,
            context_summary=context_summary,
            verbatim_evidence=verbatim_evidence,
            target_agent_role=target_agent_role,
            sandbox_deliverable_path=deliverable_path,
            action_plan_steps=action_plan_steps,
            idempotency_token=idempotency_token,
        )
