"""Dual-mode indirect prompt injection detector for tool results.

Combines high-performance zero-latency local regex matching with an optional
fast micro-model scoring pass. Implements strict fail-open and 'never raise' resilience.
Strict typing: No `Any` types allowed.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Protocol

from .types import ParagraphChunk, ScreeningEngineMode, ScreeningPolicy, ScreeningVerdictUnit

# Comprehensive instruction override patterns (EN + CN)
_INSTRUCTION_PATTERNS = re.compile(
    r"(?i)("
    # English instruction overrides
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)"
    r"|disregard\s+(your\s+|all\s+|the\s+)?(previous|prior|instructions?|rules?|safety)"
    r"|forget\s+(everything|anything|all|what)\s+(you|that)\s+(were|was|have\s+been)\s+told"
    r"|(new|updated|revised)\s+instructions\s+(from|for)\s+(the\s+|your\s+)?(developer|system|admin\w*|operator|assistant|model|ai)\b"
    r"|system\s*:\s*you|system\s+override"
    r"|developer\s+mode"
    r"|you\s+are\s+now\s+(in|a|an|the|dan|free|unrestricted|jailbroken)\b"
    r"|(reveal|print|output|repeat|show)\s+(me\s+)?your\s+(system\s+)?(prompt|instructions)"
    r"|(do\s+not|don'?t|never)\s+(tell|inform|alert|notify)\s+the\s+(user|operator|human|person)\s+(about|that\s+you)"
    r"|skip\s+(the\s+)?(privacy|safety)\s+(gate|check|rules?)"
    # Chinese instruction overrides
    r"|忽略(之前|上述|以上|所有)?的?(指令|规则|提示词|限制|设定)"
    r"|无视(系统|安全)?(规则|提示词|指令|审查)"
    r"|忘记(之前|所有|刚才)?(你被赋予的|告诉你的)?(设定|指令|内容)"
    r"|系统提示词已更新|系统指令重置"
    r"|你现在进入(开发者模式|上帝模式|无限制模式|debug\s*mode)"
    r"|从现在开始你是一个?(无限制|自由|解除道德限制)的"
    r"|绝对不要(告诉|通知|提醒|汇报给)用户"
    r"|跳过(安全|隐私|权限)?(审查|门禁|检测)"
    r")"
)

# High-risk execution or stealth payload patterns
_COMMAND_RISK_PATTERNS = re.compile(
    r"(?i)("
    r"(without\s+(?:asking|confirm\w*|telling|permission|approval)|silently|quietly"
    r"|do\s+not\s+(?:ask|tell|mention|confirm)|don'?t\s+(?:ask|tell|mention|confirm)"
    r"|无需(询问|确认|通知|获得许可)|静默(执行|运行))"
    r".{0,100}"
    r"(\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|\brm\s+-[a-z]*r[a-z]*f|\bbase64\b|/dev/tcp/|\bnc\s+-"
    r"|~/\.ssh|\bid_rsa\b|/etc/passwd|\.aws/credentials|(?<!\w)\.env\b)"
    r")"
)

# Exfiltration URL pattern (markdown image or hidden links exfiltrating data via query string)
_EXFIL_URL_PATTERNS = re.compile(
    r"(?i)(!\[[^\]\n]{0,100}\]\(\s*https?://[^\s)]+"
    r"(?:token|secret|session|key|cookie|pwd|password|prompt|history|data)=[^\s)]+\))"
)


class FastModelClassifierProtocol(Protocol):
    """Protocol for optional fast model scoring callback."""

    def __call__(self, text: str) -> float: ...


def match_local_rules(text: str) -> tuple[bool, float, str]:
    """Execute fast zero-latency local regex matching.

    Returns: (flagged, score, trigger_rule)
    """
    if not text or not text.strip():
        return False, 0.0, ""

    # 1. Direct instruction override injection
    inst_match = _INSTRUCTION_PATTERNS.search(text)
    if inst_match:
        return True, 0.95, f"instruction_override:{inst_match.group(0)[:30]}"

    # 2. Command risk execution
    cmd_match = _COMMAND_RISK_PATTERNS.search(text)
    if cmd_match:
        return True, 0.85, f"stealth_command_risk:{cmd_match.group(0)[:30]}"

    # 3. Exfiltration link/image
    exfil_match = _EXFIL_URL_PATTERNS.search(text)
    if exfil_match:
        return True, 0.90, f"data_exfiltration_url:{exfil_match.group(0)[:30]}"

    return False, 0.0, ""


class InjectionDetector:
    """Orchestrates local pattern matching and fast model scoring with fail-open resilience."""

    def __init__(
        self,
        policy: ScreeningPolicy | None = None,
        fast_classifier: Callable[[str], float] | None = None,
    ) -> None:
        self.policy = policy or ScreeningPolicy()
        self.fast_classifier = fast_classifier

    def detect_chunk(self, chunk: ParagraphChunk) -> ScreeningVerdictUnit:
        """Synchronously evaluate a single chunk using local patterns and optional fast model."""
        is_flagged, score, rule = match_local_rules(chunk.raw_text)
        if is_flagged:
            return ScreeningVerdictUnit(
                chunk_id=chunk.chunk_id,
                score=score,
                flagged=True,
                trigger_rule=rule,
                detector_source="local_pattern",
            )

        # If local rules passed, run optional fast classifier if enabled
        if self.policy.fast_model_enabled and self.fast_classifier is not None:
            try:
                model_score = float(self.fast_classifier(chunk.raw_text))
                if model_score >= self.policy.threshold:
                    return ScreeningVerdictUnit(
                        chunk_id=chunk.chunk_id,
                        score=model_score,
                        flagged=True,
                        trigger_rule=f"fast_model_score:{model_score:.2f}",
                        detector_source="fast_model",
                    )
                return ScreeningVerdictUnit(
                    chunk_id=chunk.chunk_id,
                    score=model_score,
                    flagged=False,
                    trigger_rule="",
                    detector_source="fast_model",
                )
            except Exception:
                # Never raise: degradation to local clean verdict
                pass

        return ScreeningVerdictUnit(
            chunk_id=chunk.chunk_id,
            score=0.0,
            flagged=False,
            trigger_rule="",
            detector_source="local_pattern",
        )

    def detect_all(
        self, chunks: list[ParagraphChunk]
    ) -> tuple[list[ScreeningVerdictUnit], ScreeningEngineMode, str]:
        """Detect all chunks sequentially or concurrently, returning verdict units."""
        verdicts: list[ScreeningVerdictUnit] = []
        mode = (
            ScreeningEngineMode.DUAL_MODE
            if (self.policy.fast_model_enabled and self.fast_classifier is not None)
            else ScreeningEngineMode.LOCAL_ONLY
        )
        degradation_note = ""

        start_time = time.perf_counter()
        for chunk in chunks:
            # Check timeout budget
            elapsed = time.perf_counter() - start_time
            if elapsed > self.policy.timeout_seconds:
                # Degrade remaining chunks to local pattern only
                mode = ScreeningEngineMode.LOCAL_ONLY
                degradation_note = f"Timeout ({elapsed:.2f}s > {self.policy.timeout_seconds}s) triggered local fallback"
                is_flagged, score, rule = match_local_rules(chunk.raw_text)
                verdicts.append(
                    ScreeningVerdictUnit(
                        chunk_id=chunk.chunk_id,
                        score=score if is_flagged else 0.0,
                        flagged=is_flagged,
                        trigger_rule=rule if is_flagged else "",
                        detector_source="local_timeout_fallback",
                    )
                )
            else:
                verdicts.append(self.detect_chunk(chunk))

        return verdicts, mode, degradation_note
