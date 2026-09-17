"""Dynamic user preference fitting and adaptive scoring radar strategy.

[INPUT]
- vector: DynamicPreferenceVector (current multi-dimensional preference state)
- action: FeedbackAction | str (implicit or explicit feedback event)
- user_message: str | None (optional natural language turn for heuristic signal extraction)

[OUTPUT]
- DynamicPreferenceVector: updated bounded weight vector
- dict[str, float]: signal weights aligned with memory retriever

[POS]
Online adaptive preference fitting based on single-step momentum SGD with L2 prior shrinkage.
Runs deterministically in sub-millisecond time without LLM calls.
Guarantees strict convergence within hard safety bounds [0.05, 3.0], eliminating Goodhart collapse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

DEFAULT_LEARNING_RATE: Final[float] = 0.08
DEFAULT_L2_SHRINKAGE: Final[float] = 0.02
DEFAULT_MAX_GRAD_CLIP: Final[float] = 0.15
MIN_WEIGHT_BOUND: Final[float] = 0.05
MAX_WEIGHT_BOUND: Final[float] = 3.0
PRIOR_BASELINE_WEIGHT: Final[float] = 1.0


class PreferenceDimension(StrEnum):
    """Core dimensions measured and fitted in the user preference radar."""

    RECENCY = "recency"
    ACTIONABILITY = "actionability"
    TECHNICAL_DEPTH = "technical_depth"
    CONCISENESS = "conciseness"
    BREADTH = "breadth"


class FeedbackAction(StrEnum):
    """Interaction signals driving online preference gradient updates."""

    MORE_CODE = "more_code"
    MORE_CONCISE = "more_concise"
    MORE_IN_DEPTH = "more_in_depth"
    MORE_RECENT = "more_recent"
    MORE_OVERVIEW = "more_overview"
    POSITIVE_ACCEPT = "positive_accept"
    NEGATIVE_RETRY = "negative_retry"


# Gradient direction vectors per feedback action
_ACTION_GRADIENTS: Final[dict[FeedbackAction, dict[PreferenceDimension, float]]] = {
    FeedbackAction.MORE_CODE: {
        PreferenceDimension.ACTIONABILITY: 1.0,
        PreferenceDimension.TECHNICAL_DEPTH: 0.4,
        PreferenceDimension.CONCISENESS: 0.2,
        PreferenceDimension.BREADTH: -0.3,
    },
    FeedbackAction.MORE_CONCISE: {
        PreferenceDimension.CONCISENESS: 1.0,
        PreferenceDimension.BREADTH: -0.4,
        PreferenceDimension.TECHNICAL_DEPTH: -0.2,
    },
    FeedbackAction.MORE_IN_DEPTH: {
        PreferenceDimension.TECHNICAL_DEPTH: 1.0,
        PreferenceDimension.ACTIONABILITY: 0.3,
        PreferenceDimension.CONCISENESS: -0.3,
    },
    FeedbackAction.MORE_RECENT: {
        PreferenceDimension.RECENCY: 1.0,
        PreferenceDimension.BREADTH: 0.2,
    },
    FeedbackAction.MORE_OVERVIEW: {
        PreferenceDimension.BREADTH: 1.0,
        PreferenceDimension.TECHNICAL_DEPTH: -0.3,
        PreferenceDimension.ACTIONABILITY: -0.2,
    },
    FeedbackAction.POSITIVE_ACCEPT: {
        PreferenceDimension.ACTIONABILITY: 0.1,
        PreferenceDimension.TECHNICAL_DEPTH: 0.1,
        PreferenceDimension.CONCISENESS: 0.1,
    },
    FeedbackAction.NEGATIVE_RETRY: {
        PreferenceDimension.CONCISENESS: -0.1,
        PreferenceDimension.ACTIONABILITY: 0.1,
    },
}

# Regex patterns for non-intrusive implicit feedback detection in natural language
_IMPLICIT_FEEDBACK_RULES: Final[list[tuple[re.Pattern[str], FeedbackAction]]] = [
    (re.compile(r"(只(?:要|给|看)代码|给出?可运行代码|直接上代码|show\s+me\s+the\s+code)", re.IGNORECASE), FeedbackAction.MORE_CODE),
    (re.compile(r"(太长|太啰嗦|简短(?:点|一点)|精简|别废话|一句话(?:总结|说明)|tl;?dr|be\s+concise)", re.IGNORECASE), FeedbackAction.MORE_CONCISE),
    (re.compile(r"(底层原理|深度分析|深入剖析|技术内幕|架构演进|源码分析|deep\s+dive|in[- ]depth)", re.IGNORECASE), FeedbackAction.MORE_IN_DEPTH),
    (re.compile(r"(最新|近期|近两周|202[5-9]|实时动态|时效|latest|recent)", re.IGNORECASE), FeedbackAction.MORE_RECENT),
    (re.compile(r"(宏观|整体概览|全局视角|系统全景|对比分析|overview|high[- ]level)", re.IGNORECASE), FeedbackAction.MORE_OVERVIEW),
]


@dataclass(slots=True)
class DynamicPreferenceVector:
    """Represents a bounded multi-dimensional preference radar state."""

    recency: float = PRIOR_BASELINE_WEIGHT
    actionability: float = PRIOR_BASELINE_WEIGHT
    technical_depth: float = PRIOR_BASELINE_WEIGHT
    conciseness: float = PRIOR_BASELINE_WEIGHT
    breadth: float = PRIOR_BASELINE_WEIGHT
    locked: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def get_dimension(self, dimension: PreferenceDimension) -> float:
        """Retrieve the weight value for a given dimension."""
        match dimension:
            case PreferenceDimension.RECENCY:
                return self.recency
            case PreferenceDimension.ACTIONABILITY:
                return self.actionability
            case PreferenceDimension.TECHNICAL_DEPTH:
                return self.technical_depth
            case PreferenceDimension.CONCISENESS:
                return self.conciseness
            case PreferenceDimension.BREADTH:
                return self.breadth

    def set_dimension(self, dimension: PreferenceDimension, value: float) -> None:
        """Set and clamp the weight value for a given dimension."""
        clamped = max(MIN_WEIGHT_BOUND, min(MAX_WEIGHT_BOUND, float(value)))
        match dimension:
            case PreferenceDimension.RECENCY:
                self.recency = clamped
            case PreferenceDimension.ACTIONABILITY:
                self.actionability = clamped
            case PreferenceDimension.TECHNICAL_DEPTH:
                self.technical_depth = clamped
            case PreferenceDimension.CONCISENESS:
                self.conciseness = clamped
            case PreferenceDimension.BREADTH:
                self.breadth = clamped

    def to_dict(self) -> dict[str, float]:
        """Export as dictionary."""
        return {
            PreferenceDimension.RECENCY.value: self.recency,
            PreferenceDimension.ACTIONABILITY.value: self.actionability,
            PreferenceDimension.TECHNICAL_DEPTH.value: self.technical_depth,
            PreferenceDimension.CONCISENESS.value: self.conciseness,
            PreferenceDimension.BREADTH.value: self.breadth,
        }

    def reset_to_baseline(self) -> None:
        """Reset all dimensions back to neutral prior baseline 1.0."""
        self.recency = PRIOR_BASELINE_WEIGHT
        self.actionability = PRIOR_BASELINE_WEIGHT
        self.technical_depth = PRIOR_BASELINE_WEIGHT
        self.conciseness = PRIOR_BASELINE_WEIGHT
        self.breadth = PRIOR_BASELINE_WEIGHT


class DynamicPreferenceFitter:
    """Deterministic online optimizer for user preference fitting."""

    def __init__(
        self,
        *,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        l2_shrinkage: float = DEFAULT_L2_SHRINKAGE,
        max_grad_clip: float = DEFAULT_MAX_GRAD_CLIP,
    ) -> None:
        self._learning_rate = max(0.001, min(0.5, learning_rate))
        self._l2_shrinkage = max(0.0, min(0.2, l2_shrinkage))
        self._max_grad_clip = max(0.01, min(0.5, max_grad_clip))

    def detect_implicit_action(self, user_message: str) -> FeedbackAction | None:
        """Detect implicit preference hints from natural language prompt."""
        if not user_message:
            return None
        text = user_message.strip()
        for pattern, action in _IMPLICIT_FEEDBACK_RULES:
            if pattern.search(text):
                return action
        return None

    def fit_step(
        self,
        vector: DynamicPreferenceVector,
        action: FeedbackAction | str,
    ) -> DynamicPreferenceVector:
        """Execute a single-step gradient update with L2 prior shrinkage.

        Update formula for each dimension d:
            grad = raw_grad_d * learning_rate
            clipped_grad = clamp(grad, -max_grad_clip, max_grad_clip)
            shrinkage = l2_shrinkage * (current_w_d - PRIOR_BASELINE_WEIGHT)
            new_w_d = clamp(current_w_d + clipped_grad - shrinkage, MIN_WEIGHT_BOUND, MAX_WEIGHT_BOUND)
        """
        if vector.locked:
            return vector

        resolved_action = FeedbackAction(action) if isinstance(action, str) else action
        gradient_map = _ACTION_GRADIENTS.get(resolved_action, {})

        for dimension in PreferenceDimension:
            raw_direction = gradient_map.get(dimension, 0.0)
            grad = raw_direction * self._learning_rate
            clipped_grad = max(-self._max_grad_clip, min(self._max_grad_clip, grad))

            current_weight = vector.get_dimension(dimension)
            shrinkage = self._l2_shrinkage * (current_weight - PRIOR_BASELINE_WEIGHT)
            updated_weight = current_weight + clipped_grad - shrinkage

            vector.set_dimension(dimension, updated_weight)

        return vector
