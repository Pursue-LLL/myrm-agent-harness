"""
[INPUT]: Raw provider usage dicts or NormalizedUsage instances per round in multi-turn runs.
[OUTPUT]: NormalizedUsage, TurnUsageSummary, and TurnUsageTracker with dual-count (billed vs freeze).
[POS]: myrm_agent_harness/observability/turn_usage/models.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Union


def _safe_sum(a: Optional[int], b: Optional[int]) -> Optional[int]:
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


@dataclass(frozen=True)
class NormalizedUsage:
    """归一化的单次物理调用 Token 使用量。

    提供 provider 无关的输入、输出、缓存读、缓存写标准表示。
    """
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read: Optional[int] = None
    cache_write: Optional[int] = None

    @property
    def has_cache_signal(self) -> bool:
        """检查本次调用是否携带真实缓存信号。

        若 read 或 write 大于 0，或同时显式声明非空，则视为具有有效缓存信号。
        """
        read_val = self.cache_read or 0
        write_val = self.cache_write or 0
        if read_val + write_val > 0:
            return True
        return self.cache_read is not None and self.cache_write is not None

    def merged_with(self, other: "NormalizedUsage") -> "NormalizedUsage":
        """合并最新缓存状态，用于冻结决策（The Freeze Decision）。

        - input_tokens / output_tokens 进行累加；
        - 缓存读写字段优先采用携带有效缓存信号的最新一轮（描述最终返回的前缀缓存状态），
          绝不将多次重试的 cache 粗暴叠加，防止虚增缓存深度。
        """
        new_cache_read = other.cache_read if other.has_cache_signal else self.cache_read
        new_cache_write = other.cache_write if other.has_cache_signal else self.cache_write
        return NormalizedUsage(
            input_tokens=_safe_sum(self.input_tokens, other.input_tokens),
            output_tokens=_safe_sum(self.output_tokens, other.output_tokens),
            cache_read=new_cache_read,
            cache_write=new_cache_write,
        )

    def summed_with(self, other: "NormalizedUsage") -> "NormalizedUsage":
        """绝对累加所有计数器，用于真实账单与成本归因（The Bill）。

        将每轮物理调用的 input、output、cache_read、cache_write 全部累加，
        真实反映向模型提供商支付的总账单。
        """
        return NormalizedUsage(
            input_tokens=_safe_sum(self.input_tokens, other.input_tokens),
            output_tokens=_safe_sum(self.output_tokens, other.output_tokens),
            cache_read=_safe_sum(self.cache_read, other.cache_read),
            cache_write=_safe_sum(self.cache_write, other.cache_write),
        )

    def as_anthropic(self) -> Dict[str, int]:
        """输出 Anthropic 官方 usage 形状。"""
        out: Dict[str, int] = {}
        if self.input_tokens is not None:
            out["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            out["output_tokens"] = self.output_tokens
        if self.cache_read is not None:
            out["cache_read_input_tokens"] = self.cache_read
        if self.cache_write is not None:
            out["cache_creation_input_tokens"] = self.cache_write
        return out

    def as_openai(self) -> Dict[str, Union[int, Dict[str, int]]]:
        """输出 OpenAI 标准 usage 形状（含 prompt_tokens_details.cached_tokens）。"""
        out: Dict[str, Union[int, Dict[str, int]]] = {}
        inp = self.input_tokens or 0
        outp = self.output_tokens or 0
        out["prompt_tokens"] = inp
        out["completion_tokens"] = outp
        out["total_tokens"] = inp + outp
        if self.cache_read is not None:
            out["prompt_tokens_details"] = {"cached_tokens": self.cache_read}
        return out


@dataclass
class TurnRoundRecord:
    round_index: int
    usage: NormalizedUsage
    timestamp: str


@dataclass
class TurnUsageSummary:
    session_id: str
    turn_id: str
    rounds_count: int
    billed: NormalizedUsage
    freeze_usage: NormalizedUsage
    cache_divergence_tokens: int
    created_at: str
    updated_at: str


class TurnUsageTracker:
    """管理多轮对话与单轮内多次调用（re-drive / tool loops）的双计数追踪器。

    同时维护：
    1. billed：绝对累加账单；
    2. freeze_usage：最新缓存决策状态；
    彻底解耦成本核算与前缀缓存冻结决策。
    """

    def __init__(self) -> None:
        self._turns: Dict[Tuple[str, str], List[TurnRoundRecord]] = {}
        self._billed_cache: Dict[Tuple[str, str], NormalizedUsage] = {}
        self._freeze_cache: Dict[Tuple[str, str], NormalizedUsage] = {}

    def record_round(
        self,
        session_id: str,
        turn_id: str,
        usage: NormalizedUsage,
    ) -> TurnUsageSummary:
        """记录该 turn 内发生的一次物理调用。"""
        now_iso = datetime.now(timezone.utc).isoformat()
        key = (session_id, turn_id)

        if key not in self._turns:
            self._turns[key] = []
            self._billed_cache[key] = usage
            self._freeze_cache[key] = usage
        else:
            self._billed_cache[key] = self._billed_cache[key].summed_with(usage)
            self._freeze_cache[key] = self._freeze_cache[key].merged_with(usage)

        round_idx = len(self._turns[key]) + 1
        record = TurnRoundRecord(
            round_index=round_idx,
            usage=usage,
            timestamp=now_iso,
        )
        self._turns[key].append(record)

        return self.get_summary(session_id, turn_id)

    def get_summary(self, session_id: str, turn_id: str) -> TurnUsageSummary:
        """获取指定回合的双计数汇总信息。"""
        key = (session_id, turn_id)
        if key not in self._turns:
            now_iso = datetime.now(timezone.utc).isoformat()
            empty_usage = NormalizedUsage(0, 0, 0, 0)
            return TurnUsageSummary(
                session_id=session_id,
                turn_id=turn_id,
                rounds_count=0,
                billed=empty_usage,
                freeze_usage=empty_usage,
                cache_divergence_tokens=0,
                created_at=now_iso,
                updated_at=now_iso,
            )

        records = self._turns[key]
        billed = self._billed_cache[key]
        freeze = self._freeze_cache[key]

        billed_cache_sum = (billed.cache_read or 0) + (billed.cache_write or 0)
        freeze_cache_sum = (freeze.cache_read or 0) + (freeze.cache_write or 0)
        divergence = max(0, billed_cache_sum - freeze_cache_sum)

        return TurnUsageSummary(
            session_id=session_id,
            turn_id=turn_id,
            rounds_count=len(records),
            billed=billed,
            freeze_usage=freeze,
            cache_divergence_tokens=divergence,
            created_at=records[0].timestamp,
            updated_at=records[-1].timestamp,
        )

    def write_in_shape(
        self,
        existing_usage: Dict[str, Union[int, Dict[str, int]]],
        billed: NormalizedUsage,
    ) -> Dict[str, Union[int, Dict[str, int]]]:
        """将 billed 双计数结果自适应回写至提供商原始响应形状中。

        若原响应为 OpenAI 形状（含 prompt_tokens），则保持 OpenAI 键名并更新 cached_tokens；
        若原响应为 Anthropic 形状，则使用 Anthropic 键名覆盖。
        """
        out: Dict[str, Union[int, Dict[str, int]]] = dict(existing_usage)
        if "prompt_tokens" in existing_usage or "completion_tokens" in existing_usage:
            if billed.input_tokens is not None:
                out["prompt_tokens"] = billed.input_tokens
            if billed.output_tokens is not None:
                out["completion_tokens"] = billed.output_tokens
            if billed.input_tokens is not None or billed.output_tokens is not None:
                out["total_tokens"] = (billed.input_tokens or 0) + (billed.output_tokens or 0)
            if billed.cache_read is not None:
                details = existing_usage.get("prompt_tokens_details")
                details_dict = dict(details) if isinstance(details, dict) else {}
                details_dict["cached_tokens"] = billed.cache_read
                out["prompt_tokens_details"] = details_dict
            return out

        # 默认 Anthropic 形状覆盖
        for k, v in billed.as_anthropic().items():
            out[k] = v
        return out
