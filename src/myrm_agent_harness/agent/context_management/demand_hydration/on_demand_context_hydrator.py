"""个人画像与专业偏好全域按需水合、动态即时召回与大模型原生创造力保鲜引擎。

对标《Replace 500+ Prompts》/about-me 核心架构思想，实现上下文动静解耦、双模即时水合与创造力保鲜。

[INPUT]
- messages: Sequence[BaseMessage]
- config: DemandHydrationConfig

[OUTPUT]
- OnDemandContextHydrator: 核心按需水合与创造力保鲜引擎

[POS]
- 位于 context_management/demand_hydration/on_demand_context_hydrator.py
"""

from collections.abc import Sequence
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.utils.token_estimation import estimate_context_tokens

from .demand_hydration_types import (
    DemandHydrationConfig,
    HydratedContextEnvelope,
    HydrationDecision,
    HydrationTriggerMode,
    ProfileCardCategory,
    UserMemoryCard,
)


class OnDemandContextHydrator:
    """按需上下文水合与创造力保鲜引擎。"""

    def __init__(self, config: DemandHydrationConfig | None = None) -> None:
        self.config = config or DemandHydrationConfig()
        self._cards: dict[str, UserMemoryCard] = {}

    def register_card(self, card: UserMemoryCard) -> None:
        """注册一张独立的细粒度偏好记忆卡片。"""
        self._cards[card.card_id] = card

    def register_cards(self, cards: Sequence[UserMemoryCard]) -> None:
        """批量注册记忆卡片。"""
        for card in cards:
            self._cards[card.card_id] = card

    def evaluate_hydration(
        self,
        user_prompt: str,
        explicit_command: str | None = None,
    ) -> HydrationDecision:
        """评估当前轮次是否触发水合注入，优先保障开放式创造力发散。"""
        # 1. 显式命令触发 (Explicit Trigger)
        if explicit_command:
            matched_cards = self._match_cards_by_command(explicit_command)
            if matched_cards:
                return HydrationDecision(
                    should_hydrate=True,
                    trigger_mode=HydrationTriggerMode.EXPLICIT_COMMAND,
                    hydrated_cards=matched_cards[: self.config.max_hydrated_cards_per_turn],
                    reason=f"Explicit user command [{explicit_command}] matched {len(matched_cards)} cards",
                    creativity_preserved=False,
                )

        # 2. 创造力保鲜门禁 (Creativity Preservation Bypass)
        lower_prompt = user_prompt.lower()
        if any(kw in lower_prompt for kw in self.config.creative_mode_keywords):
            return HydrationDecision(
                should_hydrate=False,
                trigger_mode=HydrationTriggerMode.CREATIVITY_BYPASS,
                hydrated_cards=[],
                reason="Creative mode detected: strictly bypassing profile injection to preserve divergent thinking",
                creativity_preserved=True,
            )

        # 3. 隐式语义路由 (Implicit Semantic Routing)
        if self.config.enable_implicit_routing:
            routed_cards = self._route_cards_by_intent(lower_prompt)
            if routed_cards:
                return HydrationDecision(
                    should_hydrate=True,
                    trigger_mode=HydrationTriggerMode.IMPLICIT_ROUTING,
                    hydrated_cards=routed_cards[: self.config.max_hydrated_cards_per_turn],
                    reason=f"Implicit semantic intent matched {len(routed_cards)} domain cards",
                    creativity_preserved=False,
                )

        # 4. 默认无匹配：保持上下文极简零污染
        return HydrationDecision(
            should_hydrate=False,
            trigger_mode=HydrationTriggerMode.IMPLICIT_ROUTING,
            hydrated_cards=[],
            reason="No domain profile match: context remains zero-pollution and lean",
            creativity_preserved=True,
        )

    def hydrate_context(
        self,
        messages: Sequence[BaseMessage],
        explicit_command: str | None = None,
    ) -> HydratedContextEnvelope:
        """根据策略决策将所需记忆卡片精准水合注入当前上下文。"""
        msg_list: list[BaseMessage] = list(messages)
        user_prompt = ""
        for m in reversed(msg_list):
            if isinstance(m, HumanMessage):
                user_prompt = str(m.content)
                break

        decision = self.evaluate_hydration(user_prompt, explicit_command=explicit_command)

        if not decision.should_hydrate or not decision.hydrated_cards:
            return HydratedContextEnvelope(
                original_messages=msg_list,
                hydrated_messages=msg_list,
                injected_tokens=0,
                decision=decision,
            )

        # 构建水合系统注入卡片
        card_blocks: list[str] = [
            f"- [{c.title}] ({c.category.value}): {c.content.strip()}" for c in decision.hydrated_cards
        ]
        hydration_text = (
            "[On-Demand Context Hydration]\n"
            "The following user-specific preferences and standards have been dynamically loaded for this turn:\n"
            + "\n".join(card_blocks)
        )
        injected_msg = SystemMessage(content=hydration_text)

        # 插入在全局系统提示之后或首部
        hydrated_messages: list[BaseMessage] = []
        if msg_list and isinstance(msg_list[0], SystemMessage):
            hydrated_messages = [msg_list[0], injected_msg, *msg_list[1:]]
        else:
            hydrated_messages = [injected_msg, *msg_list]

        injected_tokens = estimate_context_tokens([injected_msg])

        return HydratedContextEnvelope(
            original_messages=msg_list,
            hydrated_messages=hydrated_messages,
            injected_tokens=injected_tokens,
            decision=decision,
        )

    def _match_cards_by_command(self, cmd: str) -> list[UserMemoryCard]:
        """按显式命令匹配卡片。"""
        clean_cmd = cmd.strip().lower()
        if clean_cmd in ("/about-me", "/profile", "/me"):
            return list(self._cards.values())

        prefix_target = clean_cmd.split(":")[-1] if ":" in clean_cmd else clean_cmd.replace("/", "")
        matched: list[UserMemoryCard] = []
        for card in self._cards.values():
            if (
                prefix_target in card.card_id.lower()
                or prefix_target in card.category.value.lower()
                or any(prefix_target in tag.lower() for tag in card.tags)
            ):
                matched.append(card)
        return matched

    def _route_cards_by_intent(self, text: str) -> list[UserMemoryCard]:
        """依据意图分类器隐式匹配卡片。"""
        matched: list[UserMemoryCard] = []

        # 代码开发场景
        if any(w in text for w in ("python", "code", "refactor", "bug", "test", "代码", "重构", "实现")):
            matched.extend(
                [c for c in self._cards.values() if c.category in (ProfileCardCategory.CODING_STYLE, ProfileCardCategory.ARCHITECTURE_STANDARD)]
            )

        # 文案写作场景
        if any(w in text for w in ("write", "email", "post", "blog", "文案", "博客", "邮件", "行文")):
            matched.extend([c for c in self._cards.values() if c.category == ProfileCardCategory.WRITING_TONE])

        # 专业领域术语场景
        if any(w in text for w in ("glossary", "term", "domain", "术语", "业务名词")):
            matched.extend([c for c in self._cards.values() if c.category == ProfileCardCategory.DOMAIN_GLOSSARY])

        # 个人履历背景场景
        if any(w in text for w in ("who am i", "my role", "my background", "我是谁", "我的背景")):
            matched.extend([c for c in self._cards.values() if c.category == ProfileCardCategory.PERSONAL_BIO])

        # 去重保持原有顺序
        seen: set[str] = set()
        deduped: list[UserMemoryCard] = []
        for c in matched:
            if c.card_id not in seen:
                seen.add(c.card_id)
                deduped.append(c)

        return deduped
