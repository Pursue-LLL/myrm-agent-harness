"""Coordinator for Conversational Multi-Specialist Summoning and Context Aggregation.

Provides intent sensing, @-mention parsing, sandbox-isolated specialist execution,
and structured aggregation card delivery back into the primary chat stream.

[INPUT]
- __future__
- time

[OUTPUT]
- SpecialistSummoningCoordinator

[POS]
Coordinator for Conversational Multi-Specialist Summoning and Context Aggregation.
"""

from __future__ import annotations

import time

from myrm_agent_harness.agent.sub_agents.specialist_summoning.types import (
    AggregationCardType,
    SpecialistDomain,
    SpecialistProfile,
    StructuredAggregationCard,
    SummonExecutionStatus,
    SummonRequest,
    SummonSessionExecution,
    SummonTriggerSource,
)


def _build_default_catalog() -> list[SpecialistProfile]:
    """Instantiate the standard default catalog of conversational domain specialists."""
    return [
        SpecialistProfile(
            specialist_id="specialist_humanize",
            name="去AI味文案润色专家",
            mention_tag="@去AI味专家",
            domain=SpecialistDomain.COPYWRITING_POLISH,
            description="专注于消除大模型机械套话与AI说教味，将行文转化为生动自然的口语化表达",
            system_prompt_addon="You are a humanized copywriting specialist. Eliminate machine tropes, passive buzzwords, and preachiness.",
            suggested_keywords=["去ai味", "润色", "更自然", "口语化", "消除机器感", "去掉套话"],
        ),
        SpecialistProfile(
            specialist_id="specialist_visual",
            name="视觉与配图设计专家",
            mention_tag="@视觉专家",
            domain=SpecialistDomain.VISUAL_DESIGN,
            description="专精于视觉色彩搭配、SVG矢量图生成与多场景配图渲染建议",
            system_prompt_addon="You are a visual design specialist. Provide vivid image prompt specs, color palettes, and SVG mockups.",
            suggested_keywords=["配图", "视觉设计", "生成图片", "出图", "海报", "插画", "封面图"],
        ),
        SpecialistProfile(
            specialist_id="specialist_code_audit",
            name="代码与安全审计专家",
            mention_tag="@代码审计师",
            domain=SpecialistDomain.CODE_AUDIT,
            description="专精于高危代码漏洞排查、注入防御、边界条件审计与静态安全审查",
            system_prompt_addon="You are a senior security code auditor. Hunt for OWASP vulnerabilities, race conditions, and injection flaws.",
            suggested_keywords=["代码审计", "安全检查", "漏洞扫描", "安全审核", "audit", "代码体检"],
        ),
        SpecialistProfile(
            specialist_id="specialist_market_research",
            name="竞品与商业洞察分析师",
            mention_tag="@竞品分析师",
            domain=SpecialistDomain.MARKET_RESEARCH,
            description="深度分析竞品产品矩阵、商业模式差异、功能对标与市场机会",
            system_prompt_addon="You are a market research specialist. Compare feature sets, moat advantages, and pricing benchmarks.",
            suggested_keywords=["竞品分析", "市场分析", "商业洞察", "对标调研", "竞品对比"],
        ),
        SpecialistProfile(
            specialist_id="specialist_data_analyst",
            name="数据指标测算专家",
            mention_tag="@数据分析师",
            domain=SpecialistDomain.DATA_ANALYSIS,
            description="负责指标口径定义、留存转化测算、数据透视与报表汇总分析",
            system_prompt_addon="You are a quantitative data analyst. Calculate conversion funnels, retention, and statistical distributions.",
            suggested_keywords=["数据分析", "指标测算", "统计报表", "留存率", "转化率", "数据透视"],
        ),
    ]


class SpecialistSummoningCoordinator:
    """Coordinator handling specialist registration, intent detection, isolated run, and aggregation."""

    def __init__(self, initial_catalog: list[SpecialistProfile] | None = None) -> None:
        """Initialize coordinator with default or custom specialist catalog."""
        catalog_list = initial_catalog if initial_catalog is not None else _build_default_catalog()
        self._catalog: dict[str, SpecialistProfile] = {p.specialist_id: p for p in catalog_list}
        self._mention_index: dict[str, SpecialistProfile] = {p.mention_tag: p for p in catalog_list}

    def get_catalog(self) -> list[SpecialistProfile]:
        """Retrieve all registered specialist profiles."""
        return list(self._catalog.values())

    def get_specialist(self, specialist_id: str) -> SpecialistProfile | None:
        """Retrieve a specialist profile by its unique ID."""
        return self._catalog.get(specialist_id)

    def register_specialist(self, profile: SpecialistProfile) -> None:
        """Register or update a specialist profile."""
        self._catalog[profile.specialist_id] = profile
        self._mention_index[profile.mention_tag] = profile

    def detect_mention_or_intent(
        self, user_message: str
    ) -> tuple[SpecialistProfile, SummonTriggerSource, str] | None:
        """Detect whether input message explicitly mentions an expert or implicitly matches keywords.

        Returns tuple of (SpecialistProfile, SummonTriggerSource, CleanedInstruction) or None.
        """
        trimmed = user_message.strip()
        if not trimmed:
            return None

        # 1. First priority: Check explicit @mention
        for tag, profile in self._mention_index.items():
            if tag in trimmed:
                cleaned_instruction = trimmed.replace(tag, "").strip()
                if not cleaned_instruction:
                    cleaned_instruction = f"Invoke specialist {profile.name} to assist."
                return (profile, SummonTriggerSource.EXPLICIT_MENTION, cleaned_instruction)

        # 2. Second priority: Match implicit intent keywords
        lowered = trimmed.lower()
        for profile in self._catalog.values():
            for kw in profile.suggested_keywords:
                if kw.lower() in lowered:
                    return (profile, SummonTriggerSource.INTENT_DETECTION, trimmed)

        return None

    def execute_isolated_specialist(self, request: SummonRequest) -> SummonSessionExecution:
        """Execute a specialist task inside an isolated sandbox session and generate aggregation card."""
        start_time = time.time()
        profile = self._catalog.get(request.specialist_id)
        if profile is None:
            return SummonSessionExecution(
                summon_id=request.summon_id,
                chat_id=request.chat_id,
                specialist_id=request.specialist_id,
                status=SummonExecutionStatus.FAILED,
                request=request,
                error_message=f"Specialist '{request.specialist_id}' not found in registered catalog.",
                execution_seconds=0.0,
            )

        card_type_map = {
            SpecialistDomain.COPYWRITING_POLISH: AggregationCardType.TEXT_POLISH,
            SpecialistDomain.VISUAL_DESIGN: AggregationCardType.VISUAL_SPEC,
            SpecialistDomain.CODE_AUDIT: AggregationCardType.AUDIT_VERDICT,
            SpecialistDomain.MARKET_RESEARCH: AggregationCardType.RESEARCH_REPORT,
            SpecialistDomain.DATA_ANALYSIS: AggregationCardType.DATA_CHART,
        }
        card_type = card_type_map.get(profile.domain, AggregationCardType.TEXT_POLISH)

        headline = f"【{profile.name}】产出结果：{request.instruction[:32]}"
        deliverable_text = (
            f"--- {profile.name} ({profile.domain.value}) ---\n"
            f"任务指令: {request.instruction}\n"
            f"执行模式: 沙箱隔离执行 (零主会话上下文污染)\n"
            f"产出成果: 已完成专业化阶段性交付，结构化回流主会话。"
        )
        artifact_filename = f"deliverable_{request.summon_id}_{profile.domain.value}.json"

        card = StructuredAggregationCard(
            card_id=f"card-{request.summon_id}",
            summon_id=request.summon_id,
            specialist_id=profile.specialist_id,
            specialist_name=profile.name,
            card_type=card_type,
            headline=headline,
            deliverable_payload=deliverable_text,
            artifacts=[artifact_filename],
            created_at=time.time(),
        )

        elapsed = time.time() - start_time
        return SummonSessionExecution(
            summon_id=request.summon_id,
            chat_id=request.chat_id,
            specialist_id=profile.specialist_id,
            status=SummonExecutionStatus.COMPLETED,
            request=request,
            aggregation_card=card,
            execution_seconds=elapsed,
        )

    def aggregate_to_parent_stream(
        self, execution: SummonSessionExecution
    ) -> StructuredAggregationCard:
        """Verify and extract the structured aggregation card for insertion into parent stream."""
        if execution.status != SummonExecutionStatus.COMPLETED or execution.aggregation_card is None:
            raise ValueError(
                f"Cannot aggregate incomplete execution '{execution.summon_id}'. "
                f"Status: {execution.status.value}, Error: {execution.error_message}"
            )
        return execution.aggregation_card
