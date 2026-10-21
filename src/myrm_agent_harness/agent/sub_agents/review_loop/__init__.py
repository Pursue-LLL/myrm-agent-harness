"""Multi-Perspective Parallel Subagent Review & Bounded Review Loop package (Item 32).

[INPUT]
- executor
- pipeline
- prompts
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Multi-Perspective Parallel Subagent Review & Bounded Review Loop package (Item 32).

"""

from .executor import (
    BoundedReviewLoopExecutor,
    FixWorkerCallable,
    default_simulated_fix_worker,
)
from .pipeline import (
    MultiPerspectiveReviewPipeline,
    ReviewerHandler,
    default_deterministic_reviewer,
)
from .prompts import (
    CORRECTNESS_REVIEW_PROMPT,
    SIMPLICITY_REVIEW_PROMPT,
    TEST_COVERAGE_REVIEW_PROMPT,
    format_review_prompt,
    get_perspective_system_prompt,
)
from .types import (
    FindingSeverity,
    LoopRoundRecord,
    PerspectiveReviewReport,
    ReviewFinding,
    ReviewLoopResult,
    ReviewLoopStatus,
    ReviewPerspective,
)

__all__ = [
    "CORRECTNESS_REVIEW_PROMPT",
    "SIMPLICITY_REVIEW_PROMPT",
    "TEST_COVERAGE_REVIEW_PROMPT",
    "BoundedReviewLoopExecutor",
    "FindingSeverity",
    "FixWorkerCallable",
    "LoopRoundRecord",
    "MultiPerspectiveReviewPipeline",
    "PerspectiveReviewReport",
    "ReviewFinding",
    "ReviewLoopResult",
    "ReviewLoopStatus",
    "ReviewPerspective",
    "ReviewerHandler",
    "default_deterministic_reviewer",
    "default_simulated_fix_worker",
    "format_review_prompt",
    "get_perspective_system_prompt",
]
