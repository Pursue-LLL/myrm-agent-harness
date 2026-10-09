"""Facade for CJK ideographic iteration mark disambiguation and recall matching."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.matcher import (
    CjkIterationRecallMatcher,
)
from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.models import (
    CjkRecallMatchScore,
    IterationExpansionResult,
)
from myrm_agent_harness.toolkits.memory.cjk_iteration_mark.resolver import (
    IterationMarkResolver,
)


class CjkIterationMarkFacade:
    """Unified entrypoint for CJK iteration mark resolution and recall scoring."""

    def __init__(
        self,
        resolver: IterationMarkResolver | None = None,
        matcher: CjkIterationRecallMatcher | None = None,
    ) -> None:
        self._resolver: IterationMarkResolver = resolver or IterationMarkResolver()
        self._matcher: CjkIterationRecallMatcher = matcher or CjkIterationRecallMatcher(self._resolver)

    def disambiguate(self, text: str) -> IterationExpansionResult:
        """Resolve iteration marks across text and produce three-dimensional token sets."""
        return self._resolver.resolve(text)

    def match(
        self,
        query: str,
        target_text: str,
        *,
        threshold: float = 0.1,
    ) -> CjkRecallMatchScore:
        """Evaluate bidirectional recall match score taking iteration marks into account."""
        return self._matcher.match(query, target_text, threshold=threshold)


_FACADE_INSTANCE: CjkIterationMarkFacade | None = None


def get_cjk_iteration_mark_facade() -> CjkIterationMarkFacade:
    """Obtain or initialize global CjkIterationMarkFacade singleton."""
    global _FACADE_INSTANCE
    if _FACADE_INSTANCE is None:
        _FACADE_INSTANCE = CjkIterationMarkFacade()
    return _FACADE_INSTANCE
