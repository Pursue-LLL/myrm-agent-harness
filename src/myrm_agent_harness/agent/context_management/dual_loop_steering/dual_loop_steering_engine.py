"""内外双层循环实时代令引导、键盘意图分流与排队队列核心引擎。

[INPUT]
- dual_loop_steering_types.py: 契约模型 (LoopSteeringKind, KeyStrokeIntent, SteeringDirectiveStatus, SteeringDirective, DualLoopQueueSnapshot)

[OUTPUT]
- DualLoopSessionQueueLedger: 会话级双层循环代令账本与弹性取回队列
- InnerLoopSteeringInterceptor: 沙箱内核内层循环预推理代令装配钩子

[POS]
- 位于 context_management/dual_loop_steering/dual_loop_steering_engine.py
"""

from datetime import datetime, timezone
import uuid

from .dual_loop_steering_types import (
    DualLoopQueueSnapshot,
    KeyStrokeIntent,
    LoopSteeringKind,
    SteeringDirective,
    SteeringDirectiveStatus,
)


class DualLoopSessionQueueLedger:
    """会话级双层循环代令账本与排队队列管理器。"""

    def __init__(self) -> None:
        # session_id -> list of inner steering directives
        self._inner_queues: dict[str, list[SteeringDirective]] = {}
        # session_id -> list of outer follow-up directives
        self._outer_queues: dict[str, list[SteeringDirective]] = {}

    def dispatch_keystroke_intent(
        self,
        session_id: str,
        prompt_text: str,
        intent: KeyStrokeIntent,
        priority: int = 0,
    ) -> SteeringDirective | None:
        """根据输入框极简键盘手势原子分流指令到目标队列或执行撤回。

        Args:
            session_id: 会话 ID。
            prompt_text: 用户输入的指令文本。
            intent: 键盘手势意图。
            priority: 优先级数值（默认为 0）。

        Returns:
            SteeringDirective | None: 对应的代令指令实体，或撤回被取回的指令。
        """
        if intent == KeyStrokeIntent.ALT_UP_RECALL_EDIT:
            return self.recall_latest_follow_up(session_id)

        kind = (
            LoopSteeringKind.INNER_LOOP_STEER
            if intent == KeyStrokeIntent.ENTER_LIVE_STEER
            else LoopSteeringKind.OUTER_LOOP_FOLLOW_UP
        )

        directive_id = f"dir_{uuid.uuid4().hex[:10]}"
        directive = SteeringDirective(
            directive_id=directive_id,
            session_id=session_id,
            kind=kind,
            prompt_text=prompt_text.strip(),
            status=SteeringDirectiveStatus.PENDING,
            priority=priority,
            enqueued_at_iso=datetime.now(timezone.utc).isoformat(),
        )

        self.enqueue_directive(directive)
        return directive

    def enqueue_directive(self, directive: SteeringDirective) -> None:
        """显式入列指令到对应层级队列。"""
        sid = directive.session_id
        if directive.kind == LoopSteeringKind.INNER_LOOP_STEER:
            if sid not in self._inner_queues:
                self._inner_queues[sid] = []
            self._inner_queues[sid].append(directive)
        else:
            if sid not in self._outer_queues:
                self._outer_queues[sid] = []
            self._outer_queues[sid].append(directive)

    def drain_inner_steering(self, session_id: str) -> tuple[SteeringDirective, ...]:
        """原子提取当前会话内层循环所有待注入代令，并标记为 INJECTED。"""
        queue = self._inner_queues.get(session_id, [])
        if not queue:
            return ()

        drained: list[SteeringDirective] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in queue:
            if item.status == SteeringDirectiveStatus.PENDING:
                injected_item = SteeringDirective(
                    directive_id=item.directive_id,
                    session_id=item.session_id,
                    kind=item.kind,
                    prompt_text=item.prompt_text,
                    status=SteeringDirectiveStatus.INJECTED,
                    priority=item.priority,
                    enqueued_at_iso=item.enqueued_at_iso,
                    injected_at_iso=now_iso,
                )
                drained.append(injected_item)
            else:
                drained.append(item)

        # 消费完毕后清空该会话的内层队列
        self._inner_queues[session_id] = []
        return tuple(drained)

    def pop_next_outer_follow_up(self, session_id: str) -> SteeringDirective | None:
        """主任务收敛完成后顺次提取下一条外层排队项。"""
        queue = self._outer_queues.get(session_id, [])
        if not queue:
            return None

        item = queue.pop(0)
        return SteeringDirective(
            directive_id=item.directive_id,
            session_id=item.session_id,
            kind=item.kind,
            prompt_text=item.prompt_text,
            status=SteeringDirectiveStatus.EXECUTED,
            priority=item.priority,
            enqueued_at_iso=item.enqueued_at_iso,
            injected_at_iso=datetime.now(timezone.utc).isoformat(),
        )

    def recall_latest_follow_up(self, session_id: str) -> SteeringDirective | None:
        """瞬间取回外层排队队列中最新一条未执行项并就地恢复草稿编辑。"""
        queue = self._outer_queues.get(session_id, [])
        if not queue:
            return None

        # 从末尾弹出最新入列但未执行的项
        item = queue.pop()
        return SteeringDirective(
            directive_id=item.directive_id,
            session_id=item.session_id,
            kind=item.kind,
            prompt_text=item.prompt_text,
            status=SteeringDirectiveStatus.RECALLED,
            priority=item.priority,
            enqueued_at_iso=item.enqueued_at_iso,
            injected_at_iso=None,
        )

    def get_snapshot(self, session_id: str, is_busy: bool = False) -> DualLoopQueueSnapshot:
        """获取指定会话当前的双层循环大盘快照。"""
        inner = tuple(self._inner_queues.get(session_id, []))
        outer = tuple(self._outer_queues.get(session_id, []))
        return DualLoopQueueSnapshot(
            session_id=session_id,
            pending_inner_steer_count=len(inner),
            pending_outer_follow_up_count=len(outer),
            inner_queue=inner,
            outer_queue=outer,
            is_busy_navigating=is_busy,
            snapshot_at_iso=datetime.now(timezone.utc).isoformat(),
        )


class InnerLoopSteeringInterceptor:
    """沙箱内核内层循环预推理代令装配拦截器。"""

    @staticmethod
    def assemble_steered_context_turn(
        session_id: str,
        active_messages: list[dict[str, str]],
        ledger: DualLoopSessionQueueLedger,
    ) -> tuple[list[dict[str, str]], int]:
        """在工具调用完毕返回结果后、触发下一轮 LLM 推理前，非阻塞检查并原子装配代令。

        Returns:
            tuple[更新后的活跃消息列表, 成功装配注入的代令条数]
        """
        steer_directives = ledger.drain_inner_steering(session_id)
        if not steer_directives:
            return active_messages, 0

        updated_messages = list(active_messages)
        for d in steer_directives:
            steer_payload = (
                f"【用户实时中途代令纠偏 (Steering)】\n"
                f"{d.prompt_text}\n"
                f"（指导要求：请不要中断当前已有有效成果，下一动作立即吸收上述代令要求进行改向推进。）"
            )
            updated_messages.append({"role": "user", "content": steer_payload})

        return updated_messages, len(steer_directives)
