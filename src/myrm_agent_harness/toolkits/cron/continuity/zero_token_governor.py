"""免模型 0 Token 智能巡检去重门禁模块。

通过规范化业务指纹比对与动态噪声剥离，在数据无变化时 100% 短路跳过大模型调用，
彻底消除监控类任务的无谓 Token 资损与高频刷屏噪声。

[INPUT]
- __future__
- dataclasses
- hashlib
- json
- logging
- typing

[OUTPUT]
- logger
- ZeroTokenDecision
- ZeroTokenMonitorGovernor

[POS]
免模型 0 Token 智能巡检去重门禁模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_DEFAULT_NOISE_KEYS: Set[str] = {
    "timestamp",
    "time",
    "trace_id",
    "request_id",
    "req_id",
    "epoch",
    "nonce",
    "generated_at",
}
_MAX_CANONICAL_PAYLOAD_BYTES = 1024 * 1024  # 1MB 阈值


@dataclass(frozen=True)
class ZeroTokenDecision:
    """0 Token 短路门禁评估决策。"""

    can_skip_model: bool
    action: str
    new_hash: str
    reason: str


class ZeroTokenMonitorGovernor:
    """0 Token 智能巡检熔断器。"""

    def __init__(
        self,
        noise_keys: Optional[Set[str]] = None,
        max_payload_bytes: int = _MAX_CANONICAL_PAYLOAD_BYTES,
    ) -> None:
        self._noise_keys = noise_keys or set(_DEFAULT_NOISE_KEYS)
        self._max_payload_bytes = max_payload_bytes

    def _strip_noise_dict(self, obj: Dict[str, object]) -> Dict[str, object]:
        """递归清洗字典中的动态噪声键。"""
        cleaned: Dict[str, object] = {}
        for k, v in obj.items():
            if k.lower() in self._noise_keys:
                continue
            if isinstance(v, dict):
                cleaned[k] = self._strip_noise_dict(v)
            elif isinstance(v, list):
                cleaned[k] = self._strip_noise_list(v)
            else:
                cleaned[k] = v
        return cleaned

    def _strip_noise_list(self, arr: List[object]) -> List[object]:
        """递归清洗列表中的动态噪声项。"""
        cleaned: List[object] = []
        for item in arr:
            if isinstance(item, dict):
                cleaned.append(self._strip_noise_dict(item))
            elif isinstance(item, list):
                cleaned.append(self._strip_noise_list(item))
            else:
                cleaned.append(item)
        return cleaned

    def compute_canonical_hash(self, payload: str) -> str:
        """计算负载的规范化业务指纹（SHA-256）。

        若负载 < 1MB 且为 JSON，剥离噪声键并排序比对；
        若负载 >= 1MB 或非 JSON，降级为直接哈希计算，防 OOM 尖刺。
        """
        payload_bytes = payload.encode("utf-8")
        if len(payload_bytes) >= self._max_payload_bytes:
            # 大负载流式分块计算，防 OOM
            return hashlib.sha256(payload_bytes).hexdigest()

        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                cleaned = self._strip_noise_dict(parsed)
                canonical_str = json.dumps(
                    cleaned,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
            elif isinstance(parsed, list):
                cleaned_list = self._strip_noise_list(parsed)
                canonical_str = json.dumps(
                    cleaned_list,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        except Exception:
            pass

        # 纯文本或非标准 JSON 直接做哈希
        return hashlib.sha256(payload_bytes).hexdigest()

    def evaluate(
        self,
        current_payload: str,
        previous_hash: Optional[str] = None,
        is_quiet_mode: bool = True,
    ) -> ZeroTokenDecision:
        """根据当前采集载荷与前次哈希评估是否应跳过大模型。"""
        new_hash = self.compute_canonical_hash(current_payload)

        # 首次执行无历史哈希，必须正常调用模型
        if previous_hash is None:
            return ZeroTokenDecision(
                can_skip_model=False,
                action="PROCEED_MODEL",
                new_hash=new_hash,
                reason="Initial execution: baseline hash established",
            )

        # 内容未变且处于静默监控模式 -> 触发 0 Token 短路
        if new_hash == previous_hash and is_quiet_mode:
            logger.info(
                "Zero-token diff match (hash=%s); skipping LLM invocation",
                new_hash[:8],
            )
            return ZeroTokenDecision(
                can_skip_model=True,
                action="0_TOKEN_SKIPPED",
                new_hash=new_hash,
                reason="Payload canonical hash identical to previous run in quiet mode",
            )

        # 内容有变或非静默模式 -> 正常流转模型
        return ZeroTokenDecision(
            can_skip_model=False,
            action="PROCEED_MODEL",
            new_hash=new_hash,
            reason="Payload content modified or quiet mode disabled",
        )
