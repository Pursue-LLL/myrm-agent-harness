"""Cron 任务专属有界记事本与跨轮记忆承接模块。

提供 1KB 严格有界尺寸限制、原子安全落盘、损坏降级自愈与路径清洗，
杜绝定时任务“金鱼记忆”缺陷与上下文无节制膨胀。

[INPUT]
- __future__
- json
- logging
- os
- pathlib
- re

[OUTPUT]
- logger
- InvalidJobIdError
- BoundedScratchpad

[POS]
Cron 任务专属有界记事本与跨轮记忆承接模块。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_VALID_JOB_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")
_MAX_SCRATCHPAD_BYTES = 1024
_MAX_SUMMARY_CHARS = 500
_MAX_METRICS_COUNT = 20


class InvalidJobIdError(ValueError):
    """当 job_id 包含非法字符或路径遍历尝试时抛出。"""


class BoundedScratchpad:
    """Cron 任务有界持久化记事本管理器。"""

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, job_id: str) -> Path:
        """安全解析记事本路径，杜绝路径遍历攻击。"""
        if not _VALID_JOB_ID_PATTERN.match(job_id):
            raise InvalidJobIdError(
                f"Invalid job_id '{job_id}': must match {_VALID_JOB_ID_PATTERN.pattern}"
            )
        return self._storage_dir / f"{job_id}.scratchpad.json"

    def load(self, job_id: str) -> Dict[str, str]:
        """读取指定任务的记事本数据。

        若文件不存在、损坏或解析异常，则记录警告并自愈重置为空记事本。
        """
        file_path = self._resolve_path(job_id)
        if not file_path.exists():
            return {}

        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                logger.warning(
                    "Scratchpad for job %s is not a dict; self-healing reset",
                    job_id,
                )
                return {}
            # 过滤非字符串值保证纯净
            cleaned: Dict[str, str] = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    cleaned[k] = v
            return cleaned
        except Exception as exc:
            logger.warning(
                "Failed to read scratchpad for job %s: %s; self-healing reset",
                job_id,
                exc,
            )
            return {}

    def save(
        self,
        job_id: str,
        last_summary: Optional[str] = None,
        last_metrics: Optional[Dict[str, str]] = None,
    ) -> bool:
        """原子落盘保存记事本，严格限制在 1KB 预算内。"""
        file_path = self._resolve_path(job_id)
        payload: Dict[str, str] = {}

        if last_summary is not None:
            # 截断摘要，防止上下文膨胀
            payload["last_summary"] = last_summary[:_MAX_SUMMARY_CHARS]

        if last_metrics is not None:
            count = 0
            for k, v in last_metrics.items():
                if count >= _MAX_METRICS_COUNT:
                    break
                payload[f"metric_{k[:32]}"] = str(v)[:64]
                count += 1

        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > _MAX_SCRATCHPAD_BYTES:
            # 超过 1KB 则进一步截断摘要
            payload["last_summary"] = payload.get("last_summary", "")[:200]
            encoded = json.dumps(payload, ensure_ascii=False)

        # 原子写入：写 tmp 后 rename 替换
        tmp_path = file_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(encoded, encoding="utf-8")
            os.replace(tmp_path, file_path)
            return True
        except Exception as exc:
            logger.error(
                "Atomic write failed for scratchpad %s: %s",
                job_id,
                exc,
            )
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            return False

    def format_continuity_context(self, job_id: str) -> Optional[str]:
        """提取并格式化跨轮记忆上下文提示语。"""
        data = self.load(job_id)
        if not data:
            return None

        lines: list[str] = ["[Previous Execution Memory]"]
        if "last_summary" in data:
            lines.append(f"Last Summary: {data['last_summary']}")

        metrics = [
            f"{k.removeprefix('metric_')}: {v}"
            for k, v in data.items()
            if k.startswith("metric_")
        ]
        if metrics:
            lines.append("Key Metrics from Last Run: " + ", ".join(metrics))

        lines.append("Instructions: Compare today's results against the above memory.")
        return "\n".join(lines)
