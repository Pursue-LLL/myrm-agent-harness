"""Fast-path tiered intent classifier for procedural memory and reflection gating.

[INPUT]
- toolkits.memory.intent_reflection.types::IntentClassificationResult, IntentTier, ReflectionProbeProtocol
  (POS: Typed data contracts for the intent reflection subsystem.)

[OUTPUT]
- IntentLevelClassifier: Fast-path tiered intent classifier for procedural memory and reflection gating.

[POS]
Fast-path tiered intent classifier for procedural memory and reflection gating.
"""

import re

from myrm_agent_harness.toolkits.memory.intent_reflection.types import (
    IntentClassificationResult,
    IntentTier,
    ReflectionProbeProtocol,
)

_TIER_0_PATTERN = re.compile(
    r"^(好的|好的呀|好嘞|好的呢|收到|明白|继续|继续吧|接着|赞|确定|取消|退出|再见|拜拜|帮助|状态|"
    r"ok|okay|yes|no|continue|go\s*on|got\s*it|sure|cancel|quit|exit|status|help|hi|hello|hey)"
    r"[\s\.!?,，。！？]*$",
    re.IGNORECASE,
)

_TIER_1_PATTERNS = [
    re.compile(r"```(?:bash|sh|zsh|python|rust|json|yaml|go|ts|js)?[\s\S]*?```"),
    re.compile(
        r"\b(?:docker|kubectl|git|bash|shell|python|pytest|cargo|rust|pip|npm|pnpm|yarn|make|curl|wget)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:def |class |import |from |async def |function |const |let |var |package |fn )\b"
    ),
    re.compile(
        r"(?:traceback|exception|error:|segfault|panic:|syntaxerror|undefined is not a function)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:终端|命令行|代码|调试|脚本|编译|部署|重构代码|跑一下单测|运行测试)"),
]

_TIER_2_PATTERNS = [
    re.compile(r"(?:总结|调研|撰写|报告|分析|竞品|周报|方案|文档|文章|草案|翻译|润色)"),
    re.compile(
        r"\b(?:summary|summarize|analyze|analysis|article|essay|draft|report|research|translate)\b",
        re.IGNORECASE,
    ),
]


class IntentLevelClassifier:
    """Fast-path tiered intent classifier for procedural memory and reflection gating."""

    def __init__(self, probe: ReflectionProbeProtocol | None = None) -> None:
        self._probe = probe

    def classify(
        self,
        query: str,
        context: dict[str, str] | None = None,
    ) -> IntentClassificationResult:
        """Classify input query into an operational intent tier."""
        cleaned = query.strip()

        # Step 1: Empty or pure whitespace input -> Tier 0
        if not cleaned:
            return IntentClassificationResult(
                tier=IntentTier.TIER_0_FAST_PATH,
                confidence=1.0,
                matched_keywords=(),
                suggested_facets=(),
                source="heuristic",
                reason="Empty input classified into fast path.",
            )

        # Step 2: Strict short control or acknowledgement -> Tier 0
        if _TIER_0_PATTERN.match(cleaned):
            return IntentClassificationResult(
                tier=IntentTier.TIER_0_FAST_PATH,
                confidence=0.98,
                matched_keywords=(cleaned,),
                suggested_facets=(),
                source="heuristic",
                reason="Matched direct acknowledgement or flow control keyword.",
            )

        # Step 3: Tool and code execution inspection -> Tier 1
        tier_1_matches: list[str] = []
        for pat in _TIER_1_PATTERNS:
            found = pat.findall(cleaned)
            if found:
                tier_1_matches.extend(found[:3])
        if tier_1_matches:
            return IntentClassificationResult(
                tier=IntentTier.TIER_1_CODE_EXECUTION,
                confidence=0.95,
                matched_keywords=tuple(str(m) for m in tier_1_matches[:5]),
                suggested_facets=("coding", "devops", "architecture"),
                source="heuristic",
                reason="Detected code execution, CLI commands, or stack traces.",
            )

        # Step 4: Knowledge, documentation, or content synthesis -> Tier 2
        tier_2_matches: list[str] = []
        for pat in _TIER_2_PATTERNS:
            found = pat.findall(cleaned)
            if found:
                tier_2_matches.extend(found[:3])
        if tier_2_matches:
            return IntentClassificationResult(
                tier=IntentTier.TIER_2_KNOWLEDGE_CONTENT,
                confidence=0.90,
                matched_keywords=tuple(str(m) for m in tier_2_matches[:5]),
                suggested_facets=("writing", "business", "knowledge"),
                source="heuristic",
                reason="Detected knowledge, document authoring, or analytical keywords.",
            )

        # Step 5: Delegate to sidecar reflection probe if configured
        if self._probe is not None:
            try:
                probe_res = self._probe.classify(cleaned, context)
                if probe_res is not None:
                    return probe_res
            except Exception:
                # Fall back gracefully to internal heuristic on probe fault
                pass

        # Step 6: Deep reasoning for long multi-clause or paragraph queries
        if len(cleaned) >= 150 or cleaned.count("\n") >= 2:
            return IntentClassificationResult(
                tier=IntentTier.TIER_3_DEEP_REASONING,
                confidence=0.85,
                matched_keywords=(),
                suggested_facets=(
                    "global",
                    "coding",
                    "devops",
                    "architecture",
                    "writing",
                    "business",
                    "knowledge",
                ),
                source="heuristic",
                reason="Long-form composite multi-line prompt designated for deep reasoning.",
            )

        # Step 7: General default tier
        return IntentClassificationResult(
            tier=IntentTier.TIER_2_KNOWLEDGE_CONTENT,
            confidence=0.70,
            matched_keywords=(),
            suggested_facets=("knowledge", "global"),
            source="heuristic",
            reason="Unclassified conversational query defaults to general knowledge tier.",
        )
