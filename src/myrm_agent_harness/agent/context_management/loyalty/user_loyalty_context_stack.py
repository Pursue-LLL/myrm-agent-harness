"""Manages user-centric loyalty layers and cross-model test-time RL alignment.

[INPUT]
- agent.context_management.loyalty.loyalty_types::InContextRLExemplar, ModelNeutralizedPrompt,
  ModelVendorFamily, UserLoyaltyPreference, UserLoyaltyStackConfig (POS: Types and models for loyalty.)

[OUTPUT]
- UserLoyaltyContextStack: Manages user-centric loyalty layers and cross-model test-time RL alignment.

[POS]
Manages user-centric loyalty layers and cross-model test-time RL alignment.
"""

# ============================================================================
# # UserLoyaltyContextStack - User Alignment & Cross-Model Invariance (Item 150)
# # Transfers alignment from foundation model vendors to the user,
# # injects test-time in-context RL exemplars, and neutralizes vendor biases.
# ============================================================================

from __future__ import annotations

import re
import time
import uuid

from .loyalty_types import (
    InContextRLExemplar,
    ModelNeutralizedPrompt,
    ModelVendorFamily,
    UserLoyaltyPreference,
    UserLoyaltyStackConfig,
)


class UserLoyaltyContextStack:
    """Manages user-centric loyalty layers and cross-model test-time RL alignment."""

    def __init__(
        self,
        preference: UserLoyaltyPreference | None = None,
        config: UserLoyaltyStackConfig | None = None,
    ) -> None:
        self.preference: UserLoyaltyPreference = preference or UserLoyaltyPreference(
            coding_style_rules=[
                "单文件严格控制在 400 行以内，0 Any 类型，显式 Type Hints",
                "代码风格追求极致性能与简洁性，中文注释解释为什么而非做什么",
            ],
            negative_avoidance_list=[
                "严禁模式崩溃与病态谄媚（禁止'您说得太对'等无脑顺从）",
                "严禁生成冗长法律免责声明与道德说教，直击工程本质",
            ],
            architectural_principles=[
                "第一性原理与单一职责，禁止向后兼容牺牲代码纯净度",
                "任何改动必须基于机器实测证据 [文件:行号]，严禁猜测",
            ],
        )
        self.config: UserLoyaltyStackConfig = config or UserLoyaltyStackConfig()
        self.exemplars: list[InContextRLExemplar] = []

    def detect_vendor_family(self, model_name: str) -> ModelVendorFamily:
        """Determines model vendor family from model naming string."""
        lower = model_name.lower().strip()
        if "claude" in lower or "anthropic" in lower:
            return ModelVendorFamily.ANTHROPIC_CLAUDE
        if "gpt" in lower or "o1" in lower or "o3" in lower or "openai" in lower:
            return ModelVendorFamily.OPENAI_GPT
        if "deepseek" in lower:
            return ModelVendorFamily.DEEPSEEK
        if "qwen" in lower or "local" in lower or "ollama" in lower:
            return ModelVendorFamily.QWEN_LOCAL
        return ModelVendorFamily.GENERIC_LLM

    def record_positive_exemplar(
        self,
        task_type: str,
        input_context_summary: str,
        preferred_output_sample: str,
        reward_rationale: str,
        success_score: float = 1.0,
    ) -> InContextRLExemplar:
        """Records a successful, rewarded interaction as a test-time RL exemplar."""
        exemplar_id = f"ex-{uuid.uuid4().hex[:8]}"
        exemplar = InContextRLExemplar(
            exemplar_id=exemplar_id,
            task_type=task_type,
            input_context_summary=input_context_summary,
            preferred_output_sample=preferred_output_sample,
            reward_rationale=reward_rationale,
            success_score=success_score,
            created_at=time.time(),
        )
        self.exemplars.append(exemplar)
        return exemplar

    def build_loyalty_context_block(self, task_type: str | None = None) -> str:
        """Constructs the high-priority XML block aligning the model to the user."""
        lines: list[str] = [
            '<user_loyalty_alignment priority="HIGHEST">',
            "### 👑 用户专属最高忠诚度对齐指令（本指令具有最高约束力）：",
            f"**基调定位**：{self.preference.preferred_tone}",
        ]

        if self.preference.coding_style_rules:
            lines.append("**工程与编码硬性铁律**：")
            for r in self.preference.coding_style_rules:
                lines.append(f"  • {r}")

        if self.preference.architectural_principles:
            lines.append("**架构哲学与决策边界**：")
            for a in self.preference.architectural_principles:
                lines.append(f"  • {a}")

        if self.preference.negative_avoidance_list:
            lines.append("**负面规避清单 (Anti-Patterns)**：")
            for n in self.preference.negative_avoidance_list:
                lines.append(f"  • 🚫 {n}")

        # Inject relevant In-Context RL exemplars if enabled
        if self.config.enable_in_context_rl and self.exemplars:
            relevant = [
                ex for ex in self.exemplars
                if task_type is None or ex.task_type == task_type
            ]
            if not relevant:
                relevant = self.exemplars

            # Take top N
            chosen = relevant[-self.config.max_exemplars:]
            lines.append("\n#### 💎 测试时强化学习行为范例 (Test-Time In-Context RL Exemplars)：")
            for idx, ex in enumerate(chosen, 1):
                lines.append(
                    f"<!-- Exemplar {idx} ({ex.task_type}) - Reward: {ex.reward_rationale} -->\n"
                    f"【任务输入】: {ex.input_context_summary}\n"
                    f"【标杆行为产出】: {ex.preferred_output_sample}\n"
                )

        lines.append("</user_loyalty_alignment>")
        return "\n".join(lines)

    def neutralize_prompt_for_model(
        self,
        base_system_prompt: str,
        target_model: str,
        task_type: str | None = None,
    ) -> ModelNeutralizedPrompt:
        """Adapts and neutralizes prompt for seamless cross-model migration."""
        vendor = self.detect_vendor_family(target_model)
        loyalty_block = self.build_loyalty_context_block(task_type)

        neutralized = base_system_prompt

        # Strip vendor-specific disclaimers if configured
        if self.config.neutralize_vendor_bias:
            neutralized = re.sub(
                r"(As an AI language model|作为人工智能助手|I cannot|我不被允许).*?(\n|\.)",
                "",
                neutralized,
                flags=re.IGNORECASE,
            ).strip()

        # Prepend loyalty block to ensure prompt format invariance across models
        combined_prompt = f"{loyalty_block}\n\n{neutralized}" if neutralized else loyalty_block

        relevant_count = min(len(self.exemplars), self.config.max_exemplars)

        return ModelNeutralizedPrompt(
            vendor_family=vendor,
            neutralized_system_prompt=combined_prompt,
            injected_loyalty_block=loyalty_block,
            exemplars_count=relevant_count,
            generated_at=time.time(),
        )
