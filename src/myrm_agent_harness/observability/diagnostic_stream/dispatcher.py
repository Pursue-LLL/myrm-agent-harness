"""
[INPUT]: Normal message tokens, diagnostic signals, severity levels, and subscriber hooks.
[OUTPUT]: Thread-safe DiagnosticStreamDispatcher delivering dual-track decoupled stream packets.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/diagnostic_stream/dispatcher.py
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
from typing import Callable, Dict, List, Optional
import uuid

from .models import (
    DiagnosticCategory,
    DiagnosticEvent,
    DiagnosticSeverity,
    StreamPacket,
)


@dataclass
class DiagnosticStreamStats:
    """诊断事件分类与严重度聚合统计"""

    total_events: int
    by_severity: Dict[str, int]
    by_category: Dict[str, int]


class DiagnosticStreamDispatcher:
    """双轨流式派发器：物理隔离正常用户消息流与 ACP/Agent 诊断事件流"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: List[DiagnosticEvent] = []
        # 双轨订阅者回调字典: sub_id -> (session_id, callback)
        self._message_subscribers: Dict[str, tuple[str, Callable[[str], None]]] = {}
        self._diagnostic_subscribers: Dict[
            str, tuple[str, Callable[[DiagnosticEvent], None]]
        ] = {}

    def subscribe_message(
        self, session_id: str, callback: Callable[[str], None]
    ) -> str:
        """订阅正常消息通道（仅接收自然语言回答与用户输出文本）"""
        with self._lock:
            sub_id = f"sub_msg_{uuid.uuid4().hex[:8]}"
            self._message_subscribers[sub_id] = (session_id, callback)
            return sub_id

    def subscribe_diagnostic(
        self, session_id: str, callback: Callable[[DiagnosticEvent], None]
    ) -> str:
        """订阅独立诊断通道（仅接收运行时告警、重试、截断与体征事件，绝不污染正轨）"""
        with self._lock:
            sub_id = f"sub_diag_{uuid.uuid4().hex[:8]}"
            self._diagnostic_subscribers[sub_id] = (session_id, callback)
            return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """取消订阅通道"""
        with self._lock:
            self._message_subscribers.pop(sub_id, None)
            self._diagnostic_subscribers.pop(sub_id, None)

    def dispatch_message(self, session_id: str, text_delta: str) -> StreamPacket:
        """向正轨消息流派发文本增量：确保 100% 不流入诊断监听器"""
        with self._lock:
            packet = StreamPacket(
                channel="message",
                payload={"session_id": session_id, "delta": text_delta},
            )
            # 仅通知正轨消息订阅者
            for sub_id, (sub_sess, cb) in list(self._message_subscribers.items()):
                if sub_sess == session_id or sub_sess == "*":
                    try:
                        cb(text_delta)
                    except Exception:
                        pass
            return packet

    def dispatch_diagnostic(
        self,
        session_id: str,
        run_id: str,
        category: DiagnosticCategory,
        severity: DiagnosticSeverity,
        code: str,
        message: str,
        details: Optional[Dict[str, str]] = None,
    ) -> DiagnosticEvent:
        """向独立诊断通道派发诊断事件：确保 100% 不污染正轨用户消息流"""
        with self._lock:
            event = DiagnosticEvent(
                event_id=f"diag_{uuid.uuid4().hex[:10]}",
                session_id=session_id,
                run_id=run_id,
                category=category,
                severity=severity,
                code=code,
                message=message,
                details=details or {},
            )
            self._events.append(event)

            # 仅通知独立诊断订阅者（如 ACP 监控抽屉、DevTools）
            for sub_id, (sub_sess, cb) in list(self._diagnostic_subscribers.items()):
                if sub_sess == session_id or sub_sess == "*":
                    try:
                        cb(event)
                    except Exception:
                        pass

            return event

    def get_recent_diagnostics(
        self,
        session_id: Optional[str] = None,
        severity: Optional[DiagnosticSeverity] = None,
        limit: int = 50,
    ) -> List[DiagnosticEvent]:
        """获取最近过滤后的诊断事件列表"""
        with self._lock:
            res = self._events
            if session_id:
                res = [e for e in res if e.session_id == session_id]
            if severity:
                res = [e for e in res if e.severity == severity]
            return list(reversed(res[-limit:]))

    def get_stats(self) -> DiagnosticStreamStats:
        """汇总诊断事件多维分布统计"""
        with self._lock:
            by_sev: Dict[str, int] = defaultdict(int)
            by_cat: Dict[str, int] = defaultdict(int)

            for e in self._events:
                by_sev[e.severity.value] += 1
                by_cat[e.category.value] += 1

            return DiagnosticStreamStats(
                total_events=len(self._events),
                by_severity=dict(by_sev),
                by_category=dict(by_cat),
            )

    def reset(self) -> None:
        """重置所有历史记录与订阅者（用于测试隔离）"""
        with self._lock:
            self._events.clear()
            self._message_subscribers.clear()
            self._diagnostic_subscribers.clear()
