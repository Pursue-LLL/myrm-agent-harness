"""同会话就地轨迹关键帧三明治压缩器模块。

严格恪守工业级终极铁律：“A retried bot turn NEVER mints a fresh session.”
当捕获到上下文溢出（context_overflow）时，绝不新建空白会话冲刷丢失历史，
而是在同一个会话 ID 下原地就地执行三明治压缩（保留首轮目标头帧与鲜活尾帧，中程浓缩为检查点），
以瘦身后的完整上下文在原会话原地重发推理。

[INPUT]
- __future__
- dataclasses

[OUTPUT]
- CompactionResult
- InSessionTrajectoryCompactor

[POS]
同会话就地轨迹关键帧三明治压缩器模块。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """就地轨迹压缩结果实体。"""

    session_id: str
    compacted_messages: list[dict[str, str]]
    original_message_count: int
    compacted_message_count: int
    pruned_message_count: int
    estimated_original_chars: int
    estimated_compacted_chars: int
    compression_ratio: float


class InSessionTrajectoryCompactor:
    """同会话就地轨迹三明治压缩器。"""

    DEFAULT_KEEP_TAIL_COUNT: int = 4  # 保留最近 4 条最鲜活消息（2 轮交互）
    DEFAULT_KEEP_HEAD_COUNT: int = 2  # 保留头部 System 与第 1 条 User 目标

    @classmethod
    def _estimate_chars(cls, messages: list[dict[str, str]]) -> int:
        """估算消息列表总字符量。"""
        total = 0
        for msg in messages:
            total += len(msg.get("content", "")) + len(msg.get("role", ""))
        return total

    @classmethod
    def compact(
        cls,
        session_id: str,
        messages: list[dict[str, str]],
        *,
        keep_head_count: int = DEFAULT_KEEP_HEAD_COUNT,
        keep_tail_count: int = DEFAULT_KEEP_TAIL_COUNT,
    ) -> CompactionResult:
        """在原会话 ID 下就地执行三明治压缩。

        参数:
            session_id: 必须保持绝对连续的会话唯一标识符
            messages: 待压缩的原始完整会话消息列表
            keep_head_count: 保留头部系统设定与用户第一意图的数量
            keep_tail_count: 保留尾部鲜活上下文交互的数量
        """
        orig_count = len(messages)
        orig_chars = cls._estimate_chars(messages)

        # 若消息量小于保留门限，无需物理浓缩，原样返回确保幂等
        min_threshold = keep_head_count + keep_tail_count
        if orig_count <= min_threshold:
            return CompactionResult(
                session_id=session_id,
                compacted_messages=list(messages),
                original_message_count=orig_count,
                compacted_message_count=orig_count,
                pruned_message_count=0,
                estimated_original_chars=orig_chars,
                estimated_compacted_chars=orig_chars,
                compression_ratio=1.0,
            )

        # 1. 提取头部关键帧（系统提示词 + 初始业务目标）
        head_frames = list(messages[:keep_head_count])

        # 2. 提取尾部关键帧（最近新鲜交互帧与工具返回结果）
        tail_frames = list(messages[-keep_tail_count:])

        # 3. 提取并浓缩腹部中间帧
        middle_frames = messages[keep_head_count:-keep_tail_count]
        pruned_count = len(middle_frames)

        # 提炼中间动作检查点摘要
        action_summaries: list[str] = []
        for idx, msg in enumerate(middle_frames, start=1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "").strip()
            # 截取每条前 80 字符作为骨架
            snippet = content[:80].replace("\n", " ")
            if len(content) > 80:
                snippet += "..."
            action_summaries.append(f"[{role} #{idx}]: {snippet}")

        summary_body = "\n".join(action_summaries[:15])  # 最多保留前 15 步骨架
        if len(action_summaries) > 15:
            summary_body += f"\n... (其余 {len(action_summaries) - 15} 条中间轨迹已安全折叠)"

        checkpoint_message: dict[str, str] = {
            "role": "system",
            "content": (
                "[Context Checkpoint: In-Session Compacted Trajectory]\n"
                f"智能体运行时检测到上下文即将超限，已在相同会话({session_id})内原地将中间 {pruned_count} 轮"
                "繁冗工具输入输出与中间轨迹浓缩为执行骨架，首要业务目标与最新工作区状态保持 100% 完整：\n"
                f"{summary_body}\n"
                "[End of Checkpoint: Continue previous execution seamlessly without restart]"
            ),
        }

        compacted: list[dict[str, str]] = []
        compacted.extend(head_frames)
        compacted.append(checkpoint_message)
        compacted.extend(tail_frames)

        compacted_chars = cls._estimate_chars(compacted)
        ratio = round(compacted_chars / max(1, orig_chars), 3)

        return CompactionResult(
            session_id=session_id,
            compacted_messages=compacted,
            original_message_count=orig_count,
            compacted_message_count=len(compacted),
            pruned_message_count=pruned_count,
            estimated_original_chars=orig_chars,
            estimated_compacted_chars=compacted_chars,
            compression_ratio=ratio,
        )
