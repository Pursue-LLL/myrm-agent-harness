"""Engine for Dialogue State Machine and Per-State Adaptive Context Optimization.

Part of Item 128: DialogueStateMachineAndPerStateAdaptiveContextOptimizationEngine.
Implements 6-state dialogue classification, topic drift detection, two-tier token pruning,
and temporal relevance decay.

[INPUT]
- runtime.context.dialogue_state_machine_types::AdaptiveDialogueOptimizationConfig, DialogueStateKind,
  OptimizedDialogueContextResult, TokenGovernanceThresholdTier, TopicDriftAssessment, TurnStateAnnotation
  (POS: Types and models for Dialogue State Machine and Adaptive Context Optimization.)
- utils.token_estimation::estimate_context_tokens (POS: Token estimation infrastructure. Covers
  message-level tokens and bind-tools overhead for context budget / compress / summarize decisions. Aligns
  with measure_turn1_token_inventory planning SSOT.)

[OUTPUT]
- DialogueStateMachine: Classifies conversation state and assesses topic continuity.
- AdaptiveContextOptimizer: Coordinates two-stage token thresholds and state-aware context optimization.

[POS]
Engine for Dialogue State Machine and Per-State Adaptive Context Optimization.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Sequence
from typing import Final

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.runtime.context.dialogue_state_machine_types import (
    AdaptiveDialogueOptimizationConfig,
    DialogueStateKind,
    OptimizedDialogueContextResult,
    TokenGovernanceThresholdTier,
    TopicDriftAssessment,
    TurnStateAnnotation,
)
from myrm_agent_harness.utils.token_estimation import estimate_context_tokens

logger = logging.getLogger(__name__)

STOP_WORDS: Final[set[str]] = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "for",
    "to",
    "of",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "with",
    "as",
    "by",
    "from",
    "的",
    "了",
    "和",
    "是",
    "就",
    "在",
    "也",
    "有",
    "我",
    "你",
    "他",
    "她",
    "它",
}

PRONOUN_ANCHORS: Final[set[str]] = {
    "it",
    "this",
    "that",
    "these",
    "those",
    "they",
    "them",
    "这",
    "这个",
    "这款",
    "它",
    "它们",
    "该",
    "这些",
    "那些",
    "上述",
}

TERMINAL_SIGNALS: Final[set[str]] = {
    "bye",
    "goodbye",
    "done",
    "finished",
    "all set",
    "thanks, that's all",
    "再见",
    "完成",
    "搞定",
    "谢谢完成",
    "就这样",
    "结束",
    "任务完成",
}

SUPPLEMENT_SIGNALS: Final[set[str]] = {
    "also",
    "additionally",
    "furthermore",
    "besides",
    "one more thing",
    "另外",
    "补充",
    "还有",
    "还要",
    "额外要求",
    "再加一个",
}

CHATTER_PATTERNS: Final[set[str]] = {
    "hi",
    "hello",
    "hey",
    "ok",
    "okay",
    "thanks",
    "thank you",
    "got it",
    "cool",
    "你好",
    "您好",
    "哈喽",
    "收到",
    "好的",
    "明白",
    "多谢",
    "谢谢",
}


def _extract_keywords(text: str) -> list[str]:
    """Extract informative non-stopword tokens from user input."""
    raw_tokens = re.findall(r"[\w]+", text.lower())
    return [t for t in raw_tokens if t not in STOP_WORDS and len(t) > 1]


def _has_pronoun_anchor(text: str) -> bool:
    """Check whether text contains pronoun / coreference anchors."""
    lower = text.lower()
    for p in PRONOUN_ANCHORS:
        if any("\u4e00" <= c <= "\u9fff" for c in p):
            if p in lower:
                return True
        else:
            if re.search(r"\b" + re.escape(p) + r"\b", lower):
                return True
    return False


class DialogueStateMachine:
    """Classifies conversation state and assesses topic continuity."""

    def __init__(self, config: AdaptiveDialogueOptimizationConfig | None = None) -> None:
        self._config = config or AdaptiveDialogueOptimizationConfig()
        self._lock = threading.Lock()

    def assess_topic_drift(self, current_text: str, previous_text: str) -> TopicDriftAssessment:
        """Evaluate whether the current turn maintains continuity or drifts away."""
        lower_curr = current_text.lower().strip()
        lower_prev = previous_text.lower().strip()

        # If previous text is empty, treat as natural thread initiation
        if not lower_prev:
            curr_kw = _extract_keywords(lower_curr)
            return TopicDriftAssessment(
                is_drift_detected=False,
                similarity_score=1.0,
                previous_topic_keywords=[],
                current_topic_keywords=curr_kw,
                recommended_action="MAINTAIN_THREAD",
            )

        # Check for coreference / pronoun anchors and supplement markers
        has_pronoun = _has_pronoun_anchor(lower_curr)
        has_supplement = any(sig in lower_curr for sig in SUPPLEMENT_SIGNALS)
        prev_kw = _extract_keywords(lower_prev)
        curr_kw = _extract_keywords(lower_curr)

        set_prev = set(prev_kw)
        set_curr = set(curr_kw)

        if not set_prev or not set_curr:
            jaccard = 1.0 if (has_pronoun or has_supplement) else 0.5
        else:
            intersection = set_prev.intersection(set_curr)
            union = set_prev.union(set_curr)
            jaccard = round(len(intersection) / len(union), 3)

        # Coreference anchoring or supplement signals suppress topic drift
        is_drift = (jaccard < self._config.topic_drift_similarity_threshold) and not has_pronoun and not has_supplement
        action = "SOFT_ISOLATE" if is_drift else "MAINTAIN_THREAD"

        return TopicDriftAssessment(
            is_drift_detected=is_drift,
            similarity_score=jaccard,
            previous_topic_keywords=prev_kw[:6],
            current_topic_keywords=curr_kw[:6],
            recommended_action=action,
        )

    def classify_turn_state(
        self,
        current_input: str,
        turn_index: int,
        messages: Sequence[BaseMessage],
    ) -> TurnStateAnnotation:
        """Classify the latest turn into one of the six dialogue interaction states."""
        cleaned = current_input.strip().lower()

        # 1. Terminal signal check
        if any(term in cleaned for term in TERMINAL_SIGNALS):
            return TurnStateAnnotation(
                turn_index=turn_index,
                state_kind=DialogueStateKind.SESSION_TERMINAL,
                confidence_score=0.95,
                detected_intents=["terminate_session"],
                topic_drift=TopicDriftAssessment(
                    is_drift_detected=False,
                    similarity_score=1.0,
                    previous_topic_keywords=[],
                    current_topic_keywords=[],
                    recommended_action="MAINTAIN_THREAD",
                ),
                governance_tier=TokenGovernanceThresholdTier.SAFE_NORMAL,
            )

        # Retrieve prior human or assistant turn
        prior_human_text = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and msg.content != current_input:
                prior_human_text = str(msg.content)
                break

        # 2. Initial inquiry
        if turn_index <= 1 or not prior_human_text:
            curr_kw = _extract_keywords(current_input)
            return TurnStateAnnotation(
                turn_index=turn_index,
                state_kind=DialogueStateKind.INITIAL_INQUIRY,
                confidence_score=0.90,
                detected_intents=["initial_task_prompt"],
                topic_drift=TopicDriftAssessment(
                    is_drift_detected=False,
                    similarity_score=1.0,
                    previous_topic_keywords=[],
                    current_topic_keywords=curr_kw[:6],
                    recommended_action="MAINTAIN_THREAD",
                ),
                governance_tier=TokenGovernanceThresholdTier.SAFE_NORMAL,
            )

        # 3. Clarification disambiguation check
        # If previous message from assistant ended with a question, user turn is replying to clarification
        last_msg = messages[-1] if messages else None
        is_clarification = isinstance(last_msg, AIMessage) and (
            "?" in str(last_msg.content)
            or "？" in str(last_msg.content)
            or "请问" in str(last_msg.content)
            or "确认" in str(last_msg.content)
        )
        if is_clarification:
            return TurnStateAnnotation(
                turn_index=turn_index,
                state_kind=DialogueStateKind.CLARIFICATION_DISAMBIGUATION,
                confidence_score=0.92,
                detected_intents=["clarification_reply"],
                topic_drift=TopicDriftAssessment(
                    is_drift_detected=False,
                    similarity_score=1.0,
                    previous_topic_keywords=[],
                    current_topic_keywords=_extract_keywords(current_input)[:6],
                    recommended_action="MAINTAIN_THREAD",
                ),
                governance_tier=TokenGovernanceThresholdTier.SAFE_NORMAL,
            )

        drift = self.assess_topic_drift(current_input, prior_human_text)

        # 4. Requirement supplement
        if any(sig in cleaned for sig in SUPPLEMENT_SIGNALS):
            return TurnStateAnnotation(
                turn_index=turn_index,
                state_kind=DialogueStateKind.REQUIREMENT_SUPPLEMENT,
                confidence_score=0.85,
                detected_intents=["supplement_requirements"],
                topic_drift=drift,
                governance_tier=TokenGovernanceThresholdTier.SAFE_NORMAL,
            )

        # 5. Topic switch
        if drift.is_drift_detected:
            return TurnStateAnnotation(
                turn_index=turn_index,
                state_kind=DialogueStateKind.TOPIC_SWITCH,
                confidence_score=0.88,
                detected_intents=["topic_shift"],
                topic_drift=drift,
                governance_tier=TokenGovernanceThresholdTier.SAFE_NORMAL,
            )

        # 6. Follow-up probe (default continuing thread)
        return TurnStateAnnotation(
            turn_index=turn_index,
            state_kind=DialogueStateKind.FOLLOW_UP_PROBE,
            confidence_score=0.82,
            detected_intents=["follow_up"],
            topic_drift=drift,
            governance_tier=TokenGovernanceThresholdTier.SAFE_NORMAL,
        )


class AdaptiveContextOptimizer:
    """Coordinates two-stage token thresholds and state-aware context optimization."""

    def __init__(
        self,
        config: AdaptiveDialogueOptimizationConfig | None = None,
        state_machine: DialogueStateMachine | None = None,
    ) -> None:
        self._config = config or AdaptiveDialogueOptimizationConfig()
        self._state_machine = state_machine or DialogueStateMachine(self._config)
        self._lock = threading.Lock()

    def _is_chatter(self, msg: BaseMessage) -> bool:
        """Detect pure conversational filler/chatter."""
        if not isinstance(msg, HumanMessage):
            return False
        content = str(msg.content).strip().lower()
        return content in CHATTER_PATTERNS or len(content) <= 3

    def optimize_context(
        self,
        messages: Sequence[BaseMessage],
        current_input: str,
        turn_index: int,
    ) -> tuple[list[BaseMessage], OptimizedDialogueContextResult]:
        """Apply state classification, two-stage pruning, and topic-aware filtering."""
        with self._lock:
            annotation = self._state_machine.classify_turn_state(
                current_input=current_input,
                turn_index=turn_index,
                messages=messages,
            )

            raw_tokens = estimate_context_tokens(list(messages))
            tier = TokenGovernanceThresholdTier.SAFE_NORMAL
            if raw_tokens >= self._config.limit_token_threshold:
                tier = TokenGovernanceThresholdTier.LIMIT_COMPACT
            elif raw_tokens >= self._config.warning_token_threshold:
                tier = TokenGovernanceThresholdTier.WARNING_PRUNE

            # Update annotation with active tier
            annotation = annotation.model_copy(update={"governance_tier": tier})

            working_messages = list(messages)
            pruned_chatter = 0
            isolated_topics = 0

            # Tier 1: Warning threshold -> Remove pure chatter messages except head and tail
            if tier in (TokenGovernanceThresholdTier.WARNING_PRUNE, TokenGovernanceThresholdTier.LIMIT_COMPACT):
                filtered: list[BaseMessage] = []
                for idx, msg in enumerate(working_messages):
                    if idx in (0, len(working_messages) - 1):
                        filtered.append(msg)
                    elif self._is_chatter(msg):
                        pruned_chatter += 1
                    else:
                        filtered.append(msg)
                working_messages = filtered

            # Tier 2: Limit threshold or Topic Drift -> Soft isolate preceding unrelated messages
            if (
                tier == TokenGovernanceThresholdTier.LIMIT_COMPACT
                or annotation.state_kind == DialogueStateKind.TOPIC_SWITCH
            ) and len(working_messages) > 6:
                # Keep System/Turn 1 (indices 0, 1) and most recent 4 messages
                head = working_messages[:2]
                tail = working_messages[-4:]
                isolated_topics = len(working_messages) - len(head) - len(tail)
                working_messages = [
                    *head,
                    SystemMessage(content=f"<topic_drift_isolated turns={isolated_topics}/>"),
                    *tail,
                ]

            tokens_after = estimate_context_tokens(working_messages)

            result = OptimizedDialogueContextResult(
                current_annotation=annotation,
                governance_tier=tier,
                pruned_chatter_count=pruned_chatter,
                isolated_prior_topics_count=isolated_topics,
                estimated_tokens_before=raw_tokens,
                estimated_tokens_after=tokens_after,
                effective_messages_count=len(working_messages),
            )

            return working_messages, result
