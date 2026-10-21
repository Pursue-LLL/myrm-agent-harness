"""[INPUT]
- json, logging, pathlib
- typing::{Dict, Optional}
- myrm_agent_harness.observability.tracing.causal.spans::{CausalTraceTree, TraceSpan}

[OUTPUT]
- ZeroDepOTelBridge: 零硬依赖优雅降级 OpenTelemetry 遥测桥接器

[POS]
myrm_agent_harness/observability/tracing/causal/otel_bridge.py — 遥测降级接入与本地归档。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from myrm_agent_harness.observability.tracing.causal.spans import CausalTraceTree

logger = logging.getLogger(__name__)


class ZeroDepOTelBridge:
    """零硬依赖 OpenTelemetry 遥测接入桥。

    当环境中未安装 opentelemetry-sdk 时，自动降级为 no-op，直接在本地输出
    规范结构化 JSON/字典，避免可观测性反向拖累环境依赖。
    """

    def __init__(self, output_dir: Path | str | None = None) -> None:
        self.output_dir: Path | None = Path(output_dir) if output_dir else None
        self._has_otel: bool = self._detect_otel()

    def _detect_otel(self) -> bool:
        """探测当前运行环境是否安装了 OpenTelemetry SDK。"""
        try:
            import opentelemetry.trace  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def is_otel_available(self) -> bool:
        """查询 OpenTelemetry 是否可用。"""
        return self._has_otel

    def export_trace_tree(self, tree: CausalTraceTree) -> dict[str, object]:
        """导出因果 Trace 树。

        若配置了 output_dir，写入本地文件；返回归一化字典。
        """
        payload = tree.to_dict()

        if self.output_dir:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                file_path = self.output_dir / f"trace_{tree.trace_id}.json"
                file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.debug("Successfully exported trace tree to %s", file_path)
            except OSError as err:
                logger.warning("Failed to write trace tree to disk: %s", err)

        return payload
