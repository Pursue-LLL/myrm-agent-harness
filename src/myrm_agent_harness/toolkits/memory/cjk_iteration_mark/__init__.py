"""CJK ideographic iteration mark disambiguation and recall toolkit.

Implements high-fidelity chained antecedent resolution for '々' (U+3005),
generating three-dimensional token matrices to eliminate recall false negatives.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.facade import (
    CjkIterationMarkFacade,
    get_cjk_iteration_mark_facade,
)
from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.matcher import (
    CjkIterationRecallMatcher,
)
from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.models import (
    CjkRecallMatchScore,
    DisambiguatedCjkTokens,
    IterationExpansionResult,
    IterationMarkRun,
)
from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.resolver import (
    IterationMarkResolver,
)

__all__ = [
    "CjkIterationMarkFacade",
    "CjkIterationRecallMatcher",
    "CjkRecallMatchScore",
    "DisambiguatedCjkTokens",
    "IterationExpansionResult",
    "IterationMarkResolver",
    "IterationMarkRun",
    "get_cjk_iteration_mark_facade",
]
