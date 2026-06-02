"""Session-scoped JSONL usage ledger for LLM call auditing.

[INPUT]
- pathlib::Path (POS: Python 标准库)

[OUTPUT]
- UsageRecord: 单次 LLM 调用的完整元数据记录
- UsageLedger: 追加写入的 JSONL 审计日志

[POS]
Lightweight audit log recording token count, cost, latency, and model metadata for each LLM call.

"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_LEDGER_FILENAME = "usage_ledger.jsonl"


@dataclass
class _ModelAccum:
    """Accumulator for per-model breakdown in session summary."""

    calls: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class UsageRecord:
    """Single LLM call metadata for audit logging."""

    ts: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    citation_tokens: int = 0
    cost_usd: float = 0.0
    cache_savings_usd: float = 0.0
    latency_ms: float = 0.0
    ttft_ms: float = 0.0
    finish_reason: str = ""
    call_index: int = 0


@dataclass
class UsageLedger:
    """Append-only JSONL ledger for LLM call auditing.

    Usage:
        ledger = UsageLedger(Path("/session/dir"))
        ledger.append(UsageRecord(model="claude-3.5-sonnet", ...))
    """

    session_dir: Path
    _file_path: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._file_path = self.session_dir / _LEDGER_FILENAME

    def append(self, record: UsageRecord) -> None:
        """追加一条记录到 JSONL 文件。"""
        if not record.ts:
            record.ts = datetime.now(UTC).isoformat()
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False))
                f.write("\n")
        except OSError:
            logger.warning("Failed to write usage ledger: %s", self._file_path, exc_info=True)

    def load(self) -> list[UsageRecord]:
        """加载全部记录（用于会话恢复）。"""
        if not self._file_path.exists():
            return []
        records: list[UsageRecord] = []
        try:
            with self._file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        records.append(
                            UsageRecord(**{k: v for k, v in data.items() if k in UsageRecord.__dataclass_fields__})
                        )
                    except (json.JSONDecodeError, TypeError):
                        continue
        except OSError:
            logger.warning("Failed to read usage ledger: %s", self._file_path, exc_info=True)
        return records

    def get_session_summary(self) -> dict[str, object]:
        """Comprehensive session summary with per-model breakdown and cache efficiency."""
        records = self.load()
        if not records:
            return {"call_count": 0, "total_cost_usd": 0.0, "total_tokens": 0}

        total_cost = 0.0
        total_cache_savings = 0.0
        total_tokens = 0
        total_input = 0
        total_output = 0
        total_cached = 0
        total_cache_write = 0
        total_reasoning = 0
        total_citation = 0

        model_accum: dict[str, _ModelAccum] = {}
        for r in records:
            total_cost += r.cost_usd
            total_cache_savings += getattr(r, "cache_savings_usd", 0.0)
            total_tokens += r.total_tokens
            total_input += r.prompt_tokens
            total_output += r.completion_tokens
            total_cached += r.cached_tokens
            total_cache_write += r.cache_write_tokens
            total_reasoning += r.reasoning_tokens
            total_citation += r.citation_tokens

            acc = model_accum.get(r.model)
            if acc is None:
                acc = _ModelAccum()
                model_accum[r.model] = acc
            acc.calls += 1
            acc.total_tokens += r.total_tokens
            acc.input_tokens += r.prompt_tokens
            acc.output_tokens += r.completion_tokens
            acc.cached_tokens += r.cached_tokens
            acc.cost_usd += r.cost_usd

        cache_hit_rate = total_cached / total_input if total_input > 0 else 0.0

        return {
            "call_count": len(records),
            "total_cost_usd": round(total_cost, 6),
            "total_cache_savings_usd": round(total_cache_savings, 6),
            "total_tokens": total_tokens,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cached_tokens": total_cached,
            "cache_write_tokens": total_cache_write,
            "reasoning_tokens": total_reasoning,
            "citation_tokens": total_citation,
            "cache_hit_rate": round(cache_hit_rate, 4),
            "model_breakdown": {
                model: {
                    "calls": acc.calls,
                    "total_tokens": acc.total_tokens,
                    "input_tokens": acc.input_tokens,
                    "output_tokens": acc.output_tokens,
                    "cached_tokens": acc.cached_tokens,
                    "cost_usd": round(acc.cost_usd, 6),
                }
                for model, acc in model_accum.items()
            },
        }
