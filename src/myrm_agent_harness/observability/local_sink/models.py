"""
[INPUT]: Span trace data, metrics points, configuration flags, and file storage targets.
[OUTPUT]: LocalSpanRecord, LocalMetricRecord, LocalSinkStatus, and LocalDiskTelemetrySink.
[POS]: myrm_agent_harness/observability/local_sink/models.py
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Deque, Dict, List, Optional


@dataclass(frozen=True)
class LocalSpanRecord:
    trace_id: str
    span_id: str
    name: str
    start_time_iso: str
    end_time_iso: str
    duration_ms: float
    status: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalMetricRecord:
    metric_name: str
    value: float
    labels: Dict[str, str]
    timestamp_iso: str


@dataclass(frozen=True)
class LocalSinkStatus:
    is_enabled: bool
    sink_path: str
    buffered_spans_count: int
    persisted_spans_count: int
    file_size_bytes: int
    last_flush_iso: Optional[str]


class LocalDiskTelemetrySink:
    """Opt-in 本地盘可观测性落盘兜底引擎。

    在 OpenTelemetry 缺失或处于本地离线/沙箱环境下，将 Span 链路与指标安全追加至本地 JSONL 文件，
    同时在内存保留环形缓冲区（最多 500 条）支持极速前端回放与审计。
    绝不向外抛出任何 I/O 异常，坚守可观测性零侵入铁律。
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        storage_path: Optional[str] = None,
        max_buffer_size: int = 500,
    ) -> None:
        self._enabled = enabled or (os.environ.get("MYRM_LOCAL_TELEMETRY_DISK", "").lower() in ("1", "true"))
        default_dir = Path.home() / ".myrm" / "telemetry"
        self._storage_path = Path(storage_path) if storage_path else (default_dir / "spans.jsonl")
        self._buffer: Deque[LocalSpanRecord] = deque(maxlen=max_buffer_size)
        self._metrics_buffer: Deque[LocalMetricRecord] = deque(maxlen=max_buffer_size)
        self._lock = threading.Lock()
        self._persisted_count = 0
        self._last_flush: Optional[str] = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled

    def record_span(
        self,
        *,
        trace_id: str,
        span_id: str,
        name: str,
        duration_ms: float,
        status: str = "OK",
        attributes: Optional[Dict[str, str]] = None,
    ) -> LocalSpanRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        span = LocalSpanRecord(
            trace_id=trace_id,
            span_id=span_id,
            name=name,
            start_time_iso=now_iso,
            end_time_iso=now_iso,
            duration_ms=round(duration_ms, 2),
            status=status,
            attributes=attributes or {},
        )

        with self._lock:
            self._buffer.append(span)
            if self._enabled:
                self._persist_span_to_disk(span)

        return span

    def record_metric(
        self,
        *,
        metric_name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        record = LocalMetricRecord(
            metric_name=metric_name,
            value=value,
            labels=labels or {},
            timestamp_iso=now_iso,
        )
        with self._lock:
            self._metrics_buffer.append(record)

    def get_recent_spans(self, limit: int = 50) -> List[LocalSpanRecord]:
        with self._lock:
            items = list(self._buffer)
            return items[-limit:]

    def get_status(self) -> LocalSinkStatus:
        with self._lock:
            file_size = 0
            if self._storage_path.exists():
                try:
                    file_size = self._storage_path.stat().st_size
                except OSError:
                    file_size = 0

            return LocalSinkStatus(
                is_enabled=self._enabled,
                sink_path=str(self._storage_path),
                buffered_spans_count=len(self._buffer),
                persisted_spans_count=self._persisted_count,
                file_size_bytes=file_size,
                last_flush_iso=self._last_flush,
            )

    def _persist_span_to_disk(self, span: LocalSpanRecord) -> None:
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "name": span.name,
                "duration_ms": span.duration_ms,
                "status": span.status,
                "attributes": span.attributes,
                "timestamp": span.end_time_iso,
            }
            with open(self._storage_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._persisted_count += 1
            self._last_flush = datetime.now(timezone.utc).isoformat()
        except Exception:
            # 绝不让磁盘写入影响主执行
            pass
