"""静态 Persona 蒸馏、开局底噪透视与纯净创造力节食核心引擎。

[INPUT]
- context_diet_types.py: 契约模型 (ContextComponentKind, ComponentTokenAuditItem, ContextDietBudgetBill, DistilledSkillCard, ContextDietConfig)
- components 字典映射与开局配置项

[OUTPUT]
- ContextDietEngine:
  - audit_opening_budget: 审计开局底噪五要素 Token 占比与预估 TTFT 首字延迟
  - distill_persona_to_invocable_skill: 将常驻长篇人设一键蒸馏为极简骨架指示与按需技能
  - apply_unconstrained_creativity_diet: 剥离预设人设底噪，生成纯净无束缚思考上下文

[POS]
- 位于 context_management/context_diet/context_diet_engine.py
"""

from datetime import datetime, timezone
import math

from .context_diet_types import (
    ComponentTokenAuditItem,
    ContextComponentKind,
    ContextDietBudgetBill,
    ContextDietConfig,
    DistilledSkillCard,
)


class ContextDietEngine:
    """开局底噪透视审计与常驻背景按需技能化蒸馏引擎。"""

    def __init__(self, config: ContextDietConfig | None = None) -> None:
        self._config = config or ContextDietConfig()

    @property
    def config(self) -> ContextDietConfig:
        return self._config

    def audit_opening_budget(
        self,
        components: dict[ContextComponentKind, str],
        config_override: ContextDietConfig | None = None,
    ) -> ContextDietBudgetBill:
        """审计会话开局底噪要素，分解各组成部分 Token 开销并预估 TTFT 延迟。

        Args:
            components: 各要素分类与其对应的原始字符串内容。
            config_override: 可选的覆盖配置。

        Returns:
            ContextDietBudgetBill: 包含全要素分解、TTFT 延迟预估及瘦身建议的完整账单。
        """
        active_config = config_override or self._config
        token_ratio = active_config.token_char_ratio

        # 1. 统计各组件基础数据
        raw_stats: list[tuple[ContextComponentKind, int, int]] = []
        total_tokens = 0

        for kind in ContextComponentKind:
            content = components.get(kind, "")
            char_count = len(content)
            estimated = math.ceil(char_count / token_ratio) if char_count > 0 else 0
            raw_stats.append((kind, char_count, estimated))
            total_tokens += estimated

        # 2. 生成各条目细则审计项
        audit_items: list[ComponentTokenAuditItem] = []
        potential_savings = 0

        for kind, char_cnt, tokens in raw_stats:
            ratio = (tokens / total_tokens) if total_tokens > 0 else 0.0

            is_bloated = False
            recommendation = "开销处于健康精简区间。"

            if kind == ContextComponentKind.STATIC_PERSONA and char_cnt > active_config.persona_bloat_char_threshold:
                is_bloated = True
                # 蒸馏为按需技能后骨架通常仅约 35 tokens
                saved = max(0, tokens - 35)
                potential_savings += saved
                recommendation = (
                    f"常设个人/组织背景占用 {tokens} Tokens (占开局 {ratio * 100:.1f}%)，"
                    "建议一键蒸馏为按需技能 /about-me，仅在显式唤起时加载。"
                )
            elif ratio > 0.35 and tokens > 400:
                is_bloated = True
                recommendation = f"该单项占用高达 {ratio * 100:.1f}% 开局预算，建议按需水合或精简索引。"

            audit_items.append(
                ComponentTokenAuditItem(
                    component_kind=kind,
                    raw_char_count=char_cnt,
                    estimated_tokens=tokens,
                    ratio_of_budget=ratio,
                    is_bloated=is_bloated,
                    recommendation=recommendation,
                )
            )

        # 3. 计算总体窗口占比与 TTFT 耗时
        overhead_percent = (
            (total_tokens / active_config.total_window_capacity) * 100.0
            if active_config.total_window_capacity > 0
            else 0.0
        )
        estimated_ttft = (total_tokens / 1000.0) * active_config.ttft_ms_per_thousand_tokens

        return ContextDietBudgetBill(
            total_opening_tokens=total_tokens,
            total_window_capacity=active_config.total_window_capacity,
            opening_overhead_percent=round(overhead_percent, 2),
            components=tuple(audit_items),
            estimated_ttft_ms=round(estimated_ttft, 2),
            potential_savings_tokens=potential_savings,
            audited_at_iso=datetime.now(timezone.utc).isoformat(),
        )

    def distill_persona_to_invocable_skill(
        self,
        persona_text: str,
        skill_name: str = "about_me",
        trigger_command: str = "/about-me",
    ) -> DistilledSkillCard:
        """将常设冗长人设/背景文本一键蒸馏为轻量骨架指针与独立按需技能卡片。

        Args:
            persona_text: 原始常驻背景全量内容。
            skill_name: 技能唯一语义标识。
            trigger_command: 显式触发命令。

        Returns:
            DistilledSkillCard: 包含骨架指针与全量按需技能内容的卡片契约。
        """
        token_ratio = self._config.token_char_ratio
        orig_tokens = math.ceil(len(persona_text) / token_ratio) if persona_text else 0

        skeleton_pointer = (
            f"[按需背景已归档为技能 `{skill_name}` (触发命令: `{trigger_command}`)]。"
            "日常通用会话保持中立纯净推理；仅当用户显式调用或明确询问背景时按需加载完整画像。"
        )
        skeleton_tokens = math.ceil(len(skeleton_pointer) / token_ratio)
        savings = max(0, orig_tokens - skeleton_tokens)

        return DistilledSkillCard(
            skill_name=skill_name,
            trigger_command=trigger_command,
            skeleton_pointer=skeleton_pointer,
            full_content=persona_text,
            token_savings=savings,
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )

    def apply_unconstrained_creativity_diet(
        self,
        components: dict[ContextComponentKind, str],
        preserve_skeleton_pointer: bool = False,
    ) -> dict[ContextComponentKind, str]:
        """开启纯净思维沙箱模式：剥离常驻人设偏好底噪，释放模型原生推理极限。

        Args:
            components: 原始开局上下文组件映射。
            preserve_skeleton_pointer: 是否在 STATIC_PERSONA 保留极简骨架指示词。

        Returns:
            dict[ContextComponentKind, str]: 经节食精简后的纯净上下文映射。
        """
        purified = dict(components)

        if not preserve_skeleton_pointer:
            # 彻底清空常设人设，零偏好直面问题
            purified[ContextComponentKind.STATIC_PERSONA] = ""
        else:
            # 仅保留中立骨架指引
            purified[ContextComponentKind.STATIC_PERSONA] = (
                "[纯净思维模式激活] 忽略特定主体预设偏好与背景包袱，采用原生第一性原理进行深度逻辑推演与无束缚创作。"
            )

        return purified
