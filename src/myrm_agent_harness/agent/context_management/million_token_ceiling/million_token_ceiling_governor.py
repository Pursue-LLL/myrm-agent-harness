"""百万 Token 超大上下文动态自适应压实、延迟与成本双轨绝对上限守卫引擎。

解决超大模型（GPT-6/Gemini 1M+）按百分比推高阈值引发的压缩饥饿（Compaction Starvation）、
首字延迟飙升与账单雪崩问题。

[INPUT]
- messages: Sequence[BaseMessage]
- config: MillionTokenCeilingConfig

[OUTPUT]
- MillionTokenCeilingGovernor: 核心双轨治理守卫引擎
- execute_compaction(): 阶梯式压实处理入口

[POS]
- 位于 context_management/million_token_ceiling/million_token_ceiling_governor.py
"""

from collections.abc import Sequence
import json
from pathlib import Path
import time

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.utils.token_estimation import estimate_context_tokens

from .million_token_ceiling_types import (
    CompactionTierAction,
    ContextBudgetForecast,
    MillionTokenCeilingConfig,
    MillionTokenCompactionResult,
    OffloadedToolArtifact,
)


class MillionTokenCeilingGovernor:
    """超大上下文双轨动态压实与延迟成本绝对上限守卫。"""

    def __init__(
        self,
        config: MillionTokenCeilingConfig | None = None,
        default_storage_dir: Path | None = None,
    ) -> None:
        self.config = config or MillionTokenCeilingConfig()
        self.default_storage_dir = default_storage_dir

    def calculate_forecast(
        self,
        current_tokens: int,
        compacted_tokens: int | None = None,
    ) -> ContextBudgetForecast:
        """评估当前 Token 压力下的首字延迟 (TTFT) 与单轮调用成本预估。"""
        tokens_for_calc = max(0, current_tokens)
        projected_ttft_ms = self.config.base_ttft_ms + (
            (tokens_for_calc / 10_000.0) * self.config.ttft_ms_per_10k_tokens
        )
        projected_cost = (tokens_for_calc / 1000.0) * self.config.cost_per_1k_input_tokens_usd

        saved_tokens = 0
        saved_cost = 0.0
        if compacted_tokens is not None and compacted_tokens < tokens_for_calc:
            saved_tokens = tokens_for_calc - compacted_tokens
            saved_cost = (saved_tokens / 1000.0) * self.config.cost_per_1k_input_tokens_usd

        # 核心判定：传统按比例阈值 > 软上限，且当前 tokens 已超过软上限
        is_starving = (
            self.config.naive_ratio_threshold > self.config.operational_soft_ceiling
            and tokens_for_calc >= self.config.operational_soft_ceiling
        )

        return ContextBudgetForecast(
            current_tokens=tokens_for_calc,
            effective_threshold=self.config.effective_compress_threshold,
            physical_limit=self.config.physical_context_limit,
            operational_soft_ceiling=self.config.operational_soft_ceiling,
            operational_hard_ceiling=self.config.operational_hard_ceiling,
            projected_ttft_ms=round(projected_ttft_ms, 2),
            projected_turn_cost_usd=round(projected_cost, 6),
            tokens_saved_by_compaction=saved_tokens,
            cost_saved_usd=round(saved_cost, 6),
            compaction_starvation_prevented=is_starving,
        )

    def determine_tier_action(self, current_tokens: int) -> CompactionTierAction:
        """根据当前 Token 水位判定应该激活的压实阶段。"""
        if current_tokens >= int(self.config.physical_context_limit * 0.95):
            return CompactionTierAction.TIER3_EMERGENCY_GUARD
        if current_tokens >= self.config.effective_hard_ceiling:
            return CompactionTierAction.TIER2_ROLLING_SUMMARY
        if current_tokens >= self.config.effective_compress_threshold:
            return CompactionTierAction.TIER1_OFFLOAD_TOOLS
        return CompactionTierAction.NONE

    def execute_compaction(
        self,
        messages: Sequence[BaseMessage],
        storage_dir: Path | None = None,
    ) -> MillionTokenCompactionResult:
        """执行阶梯式渐进压实管道。"""
        msg_list: list[BaseMessage] = list(messages)
        before_tokens = estimate_context_tokens(msg_list)
        tier = self.determine_tier_action(before_tokens)

        if tier == CompactionTierAction.NONE:
            forecast = self.calculate_forecast(before_tokens, compacted_tokens=before_tokens)
            return MillionTokenCompactionResult(
                tier_action=CompactionTierAction.NONE,
                before_tokens=before_tokens,
                after_tokens=before_tokens,
                messages=msg_list,
                forecast=forecast,
                is_compacted=False,
            )

        target_dir = storage_dir or self.default_storage_dir or Path(".context/tools")
        target_dir.mkdir(parents=True, exist_ok=True)

        offloaded_artifacts: list[OffloadedToolArtifact] = []

        # 执行 Tier 1：工具结果外部化
        msg_list, offloaded_artifacts = self._offload_tool_outputs(
            msg_list=msg_list,
            target_dir=target_dir,
        )

        mid_tokens = estimate_context_tokens(msg_list)
        final_tier = tier

        # 如果原计划为 Tier 2，或 Tier 1 执行后仍然越过硬上限，则触发 Tier 2 增量滚动摘要
        if tier in (CompactionTierAction.TIER2_ROLLING_SUMMARY, CompactionTierAction.TIER3_EMERGENCY_GUARD) or (
            mid_tokens >= self.config.effective_hard_ceiling
        ):
            msg_list = self._perform_rolling_summary(msg_list)
            final_tier = (
                CompactionTierAction.TIER3_EMERGENCY_GUARD
                if tier == CompactionTierAction.TIER3_EMERGENCY_GUARD
                else CompactionTierAction.TIER2_ROLLING_SUMMARY
            )

        after_tokens = estimate_context_tokens(msg_list)
        forecast = self.calculate_forecast(before_tokens, compacted_tokens=after_tokens)

        return MillionTokenCompactionResult(
            tier_action=final_tier,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            offloaded_artifacts=offloaded_artifacts,
            messages=msg_list,
            forecast=forecast,
            is_compacted=after_tokens < before_tokens,
        )

    def _offload_tool_outputs(
        self,
        msg_list: list[BaseMessage],
        target_dir: Path,
    ) -> tuple[list[BaseMessage], list[OffloadedToolArtifact]]:
        """执行 Tier 1 工具内容外部化落盘。"""
        new_messages: list[BaseMessage] = []
        offloaded: list[OffloadedToolArtifact] = []
        total_len = len(msg_list)
        protect_start_idx = max(0, total_len - self.config.protected_recent_turns * 2)

        for idx, msg in enumerate(msg_list):
            if idx >= protect_start_idx or not isinstance(msg, ToolMessage):
                new_messages.append(msg)
                continue

            raw_content = str(msg.content)
            content_tokens = max(1, len(raw_content) // 4)

            # 低于最小外部化阈值则保留在上下文，不产生碎片
            if content_tokens < self.config.min_tool_offload_tokens:
                new_messages.append(msg)
                continue

            tool_call_id = msg.tool_call_id or f"call_{idx}_{int(time.time() * 1000)}"
            tool_name = getattr(msg, "name", "tool") or "tool"
            file_name = f"{tool_call_id}.json"
            file_path = target_dir / file_name

            payload = {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "content": raw_content,
                "token_estimate": content_tokens,
                "timestamp": time.time(),
            }
            file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            ref_handle = f"ref://context/tools/{tool_call_id}"
            preview = raw_content[:150].replace("\n", " ").strip()
            compacted_text = (
                f"[Tool Output Offloaded to Storage]\n"
                f"Reference: {ref_handle}\n"
                f"Tool: {tool_name}\n"
                f"Original Size: ~{content_tokens} tokens\n"
                f"Preview: {preview}...\n"
                f"(Recoverable via reference handle)"
            )

            replacement_msg = ToolMessage(
                content=compacted_text,
                tool_call_id=tool_call_id,
                name=tool_name,
            )
            new_messages.append(replacement_msg)

            offloaded.append(
                OffloadedToolArtifact(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    original_tokens=content_tokens,
                    ref_handle=ref_handle,
                    disk_path=str(file_path),
                    preview_snippet=preview,
                    created_at_epoch=time.time(),
                )
            )

        return new_messages, offloaded

    def _perform_rolling_summary(self, msg_list: list[BaseMessage]) -> list[BaseMessage]:
        """执行 Tier 2 历史多轮交互增量滚动摘要。"""
        if len(msg_list) <= self.config.protected_recent_turns * 2 + 1:
            return msg_list

        protect_count = self.config.protected_recent_turns * 2
        history_to_compress = msg_list[:-protect_count]
        recent_messages = msg_list[-protect_count:]

        preserved_prefix: list[BaseMessage] = []
        middle_messages: list[BaseMessage] = []

        for m in history_to_compress:
            if isinstance(m, SystemMessage) and not middle_messages:
                preserved_prefix.append(m)
            else:
                middle_messages.append(m)

        if not middle_messages:
            return msg_list

        summary_points: list[str] = []
        for m in middle_messages:
            role = "User" if isinstance(m, HumanMessage) else "Assistant" if isinstance(m, AIMessage) else "Tool"
            snippet = str(m.content)[:80].replace("\n", " ").strip()
            summary_points.append(f"- {role}: {snippet}")

        collapsed_text = (
            "[Historical Turns Rolling Compacted]\n"
            f"Archived turns count: {len(middle_messages)}\n"
            "Key milestones & context progression:\n"
            + "\n".join(summary_points[:6])
            + ("\n... [older interactions collapsed]" if len(summary_points) > 6 else "")
        )

        summary_msg = SystemMessage(content=collapsed_text)
        return [*preserved_prefix, summary_msg, *recent_messages]

    def restore_offloaded_tool(self, disk_path: Path | str) -> str:
        """从持久化磁盘中无损重水合工具原始输出。"""
        path = Path(disk_path)
        if not path.exists():
            raise FileNotFoundError(f"Offloaded tool artifact not found: {path}")

        raw_data = json.loads(path.read_text(encoding="utf-8"))
        content = raw_data.get("content", "")
        return str(content)
