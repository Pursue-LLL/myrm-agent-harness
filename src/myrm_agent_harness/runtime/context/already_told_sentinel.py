"""Already-told intent sentinel: detects retrospective instruction references and recalls the original user instruction.

[INPUT]
- runtime.context.already_told_sentinel_types::HistoricalTurnInput, InstructionRecallResult,
  ProvenanceCardPayload, RecallStatus (POS: Types and models for the already-told intent sentinel and
  instruction recall.)

[OUTPUT]
- AlreadyToldIntentSentinel: Sentinel for detecting 'already told' retrospective intents and recalling
  original user instructions.

[POS]
Already-told intent sentinel: detects retrospective instruction references and recalls the original user
instruction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import ClassVar

from myrm_agent_harness.runtime.context.already_told_sentinel_types import (
    HistoricalTurnInput,
    InstructionRecallResult,
    ProvenanceCardPayload,
    RecallStatus,
)


class AlreadyToldIntentSentinel:
    """Sentinel for detecting 'already told' retrospective intents and recalling original user instructions."""

    CHINESE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"(我|你)?(刚才|刚|前面|之前|先前)(不是)?(都)?(已经)?(说过|讲过|交代过|提过|规定过|说了|讲了|交代了)"
        ),
        re.compile(r"我(刚才|前面|之前)(不是)?(有|提|说|讲|交代)"),
        re.compile(r"(看|参考)(一下)?前(面)?(的)?(要求|约定|规定|内容)"),
        re.compile(r"按(照)?(原先|之前|前面)(说的)?办"),
        re.compile(r"之前不是定了吗"),
    ]

    ENGLISH_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"(?:as\s+)?(?:i\s+)?already\s+(?:told|said|mentioned|instructed)\s+you(?:\s+(?:earlier|before))?",
            re.IGNORECASE,
        ),
        re.compile(r"(?:as\s+)?(?:i\s+)?mentioned\s+earlier", re.IGNORECASE),
        re.compile(r"(?:as\s+)?(?:i\s+)?said\s+before", re.IGNORECASE),
        re.compile(r"refer\s+to\s+(?:the\s+)?(?:previous|earlier)\s+instruction", re.IGNORECASE),
        re.compile(r"previously\s+(?:stated|mentioned|instructed)", re.IGNORECASE),
    ]

    NOISE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"^(我|你|我们|大家|that|it|as)?\s*"),
        re.compile(r"(吗|呀|吧|哈|！|!|\?|？|\.|。)+$"),
    ]

    CONSTRAINT_KEYWORDS: ClassVar[list[str]] = [
        "不要",
        "别",
        "严禁",
        "禁止",
        "必须",
        "只能",
        "切勿",
        "don't",
        "must",
        "never",
        "only",
    ]

    STOP_WORDS: ClassVar[set[str]] = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "to",
        "in",
        "on",
        "of",
        "and",
        "or",
        "for",
        "with",
        "this",
        "that",
        "as",
        "i",
        "you",
        "my",
        "your",
        "use",
        "using",
        "please",
        "we",
        "our",
    }

    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self.confidence_threshold = confidence_threshold

    def inspect_and_recall(
        self,
        user_query: str,
        historical_turns: Sequence[HistoricalTurnInput],
    ) -> InstructionRecallResult:
        """Inspect the current user query, detect retrospective intent, and recall historical instruction."""
        clean_query = user_query.strip()
        matched_pattern = self._detect_pattern(clean_query)

        if not matched_pattern:
            return InstructionRecallResult(
                detected=False,
                trigger_pattern=None,
                extracted_cue=None,
                status=RecallStatus.NOT_DETECTED,
                matched_turn_index=None,
                matched_instruction=None,
                confidence_score=0.0,
                system_injection_block=None,
                provenance_card=ProvenanceCardPayload(
                    detected=False,
                    status=RecallStatus.NOT_DETECTED.value,
                ),
            )

        extracted_cue = self._extract_cue(clean_query, matched_pattern)
        best_turn, best_score = self._search_history(extracted_cue, historical_turns)

        if best_turn is not None and best_score >= self.confidence_threshold:
            system_injection = self._format_injection_block(
                turn_index=best_turn.turn_index,
                instruction=best_turn.content,
                confidence=best_score,
            )
            card = ProvenanceCardPayload(
                detected=True,
                trigger_pattern=matched_pattern,
                cue=extracted_cue,
                matched_turn_index=best_turn.turn_index,
                matched_instruction=best_turn.content,
                confidence=round(best_score, 3),
                status=RecallStatus.RECALLED_AND_ENFORCED.value,
            )
            return InstructionRecallResult(
                detected=True,
                trigger_pattern=matched_pattern,
                extracted_cue=extracted_cue,
                status=RecallStatus.RECALLED_AND_ENFORCED,
                matched_turn_index=best_turn.turn_index,
                matched_instruction=best_turn.content,
                confidence_score=round(best_score, 3),
                system_injection_block=system_injection,
                provenance_card=card,
            )

        # Fallback if intent was detected but no high-confidence historical turn was located
        card = ProvenanceCardPayload(
            detected=True,
            trigger_pattern=matched_pattern,
            cue=extracted_cue,
            matched_turn_index=None,
            matched_instruction=None,
            confidence=round(best_score, 3),
            status=RecallStatus.FALLBACK_WARN.value,
        )
        return InstructionRecallResult(
            detected=True,
            trigger_pattern=matched_pattern,
            extracted_cue=extracted_cue,
            status=RecallStatus.FALLBACK_WARN,
            matched_turn_index=None,
            matched_instruction=None,
            confidence_score=round(best_score, 3),
            system_injection_block=None,
            provenance_card=card,
        )

    def _detect_pattern(self, query: str) -> str | None:
        for pat in self.CHINESE_PATTERNS:
            m = pat.search(query)
            if m:
                return m.group(0)
        for pat in self.ENGLISH_PATTERNS:
            m = pat.search(query)
            if m:
                return m.group(0)
        return None

    def _extract_cue(self, query: str, matched_pattern: str | None) -> str:
        cue = query
        if matched_pattern:
            cue = cue.replace(matched_pattern, "")
        for noise in self.NOISE_PATTERNS:
            cue = noise.sub("", cue).strip()
        # Strip leading/trailing punctuations
        cue = re.sub(r"^[,，:：;；\s]+|[,，:：;；\s]+$", "", cue)
        return cue.strip()

    def _search_history(
        self,
        cue: str,
        turns: Sequence[HistoricalTurnInput],
    ) -> tuple[HistoricalTurnInput | None, float]:
        user_turns = [t for t in turns if t.role.lower() in ("user", "human")]
        if not user_turns:
            return None, 0.0

        cue_clean = cue.lower().strip()
        all_tokens = set(re.findall(r"[\w]+", cue_clean))
        content_tokens = {t for t in all_tokens if t not in self.STOP_WORDS and len(t) > 1}
        cue_tokens = content_tokens if content_tokens else all_tokens

        best_turn: HistoricalTurnInput | None = None
        best_score = 0.0

        for turn in user_turns:
            content_clean = turn.content.lower().strip()
            score = 0.0

            if cue_clean and cue_clean in content_clean:
                score += 0.70
            elif cue_tokens:
                turn_tokens = set(re.findall(r"[\w]+", content_clean))
                common = cue_tokens.intersection(turn_tokens)
                if common:
                    overlap_ratio = len(common) / max(len(cue_tokens), 1)
                    score += 0.55 * overlap_ratio

            # Extra weight if historical instruction contains strict constraint signals
            for kw in self.CONSTRAINT_KEYWORDS:
                if kw in content_clean:
                    score += 0.15
                    break

            if score > best_score:
                best_score = score
                best_turn = turn

        # If user query was general (no distinct cue) or no strong match, fall back to recent constraint turn
        if best_score < 0.5 and not cue_clean:
            for turn in reversed(user_turns):
                for kw in self.CONSTRAINT_KEYWORDS:
                    if kw in turn.content.lower():
                        return turn, 0.65
            if user_turns:
                return user_turns[0], 0.55

        return best_turn, min(best_score, 1.0)

    @staticmethod
    def _format_injection_block(turn_index: int, instruction: str, confidence: float) -> str:
        return (
            f'<system_verified_historical_user_instruction turn="{turn_index}" confidence="{confidence:.2f}">\n'
            f"[SYSTEM VERIFIED HISTORICAL USER INSTRUCTION]\n"
            f"- 来源轮次: #{turn_index}\n"
            f"- 用户历史原话: {instruction.strip()}\n"
            f"- 执行约束: 系统已精准调阅用户在早期会话中明确确立的上述规则。执行引擎必须严格遵守，严禁要求用户重复交代！\n"
            f"</system_verified_historical_user_instruction>"
        )
