"""Eval Search/Test Set Leakage Guard & Anti-Contamination Isolation.

[INPUT]
- EvalCase, EvalCaseSplit: core protocol dataset split structures
- SkillRecord / Trajectory: candidate variant evolution context

[OUTPUT]
- LeakageAuditResult: audit record for prompt leakage detection
- filter_search_cases_for_proposer: direct case isolation filter
- filter_trajectories_for_proposer: indirect execution trace isolation filter
- partition_dataset_split: stratified auto-split algorithm

[POS]
Part of the closed-source eval harness framework. Implements Meta-Harness
(arxiv:2603.28052) Dual-Split Protocol to physically block test-set leakage
to variant proposers, preventing Goodhart's law and shortcut overfitting.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from .protocols import EvalCase

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LeakageAuditResult:
    """Audit result for prompt inspection against held-out test contamination."""

    has_leakage: bool
    leaked_case_indices: list[int] = field(default_factory=list)
    detected_snippets: list[str] = field(default_factory=list)
    remediation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "has_leakage": self.has_leakage,
            "leaked_case_indices": list(self.leaked_case_indices),
            "detected_snippets": list(self.detected_snippets),
            "remediation": self.remediation,
        }


def is_test_case_spec(item: object) -> bool:
    """Deterministically check if an object is designated as a test-split case."""
    if isinstance(item, EvalCase):
        return item.is_test_set

    if isinstance(item, dict):
        raw_split = str(item.get("split", "")).strip().lower()
        if raw_split in ("test", "test_set", "hard", "hard_subset", "hardsubset"):
            return True
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            meta_split = str(metadata.get("split", "")).strip().lower()
            if meta_split in ("test", "test_set", "hard", "hard_subset", "hardsubset"):
                return True

    return False


def filter_search_cases_for_proposer(
    cases: Sequence[dict[str, object] | EvalCase],
) -> list[dict[str, object] | EvalCase]:
    """Physically filter out held-out test cases before exposing to proposer LLM.

    Only cases tagged as SEARCH or untagged legacy cases (default SEARCH) pass.
    """
    if not cases:
        return []

    return [c for c in cases if not is_test_case_spec(c)]


def filter_trajectories_for_proposer(
    trajectories: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Filter execution trajectories derived from held-out test evaluations.

    Prevents indirect trace leakage where LLM extracts ground-truth assertions
    from stack traces or execution errors generated during test-set runs.
    """
    clean_traces: list[dict[str, object]] = []
    for trace in trajectories:
        split_tag = str(trace.get("split", "")).strip().lower()
        if split_tag in ("test", "test_set", "hard_subset"):
            continue
        meta = trace.get("metadata")
        if isinstance(meta, dict):
            meta_split = str(meta.get("split", "")).strip().lower()
            if meta_split in ("test", "test_set", "hard_subset"):
                continue
        clean_traces.append(trace)
    return clean_traces


def audit_proposer_prompt_for_leakage(
    prompt_text: str,
    test_cases: Sequence[dict[str, object] | EvalCase],
    min_match_len: int = 16,
) -> LeakageAuditResult:
    """Audit a generated prompt to ensure no distinctive test-set spans leak through."""
    if not prompt_text or not test_cases:
        return LeakageAuditResult(has_leakage=False)

    leaked_indices: list[int] = []
    snippets: list[str] = []

    for idx, case in enumerate(test_cases):
        msg = case.message if isinstance(case, EvalCase) else str(case.get("message", ""))
        msg_clean = msg.strip()
        if len(msg_clean) >= min_match_len and msg_clean in prompt_text:
            leaked_indices.append(idx)
            snippets.append(msg_clean[:40])

    if leaked_indices:
        return LeakageAuditResult(
            has_leakage=True,
            leaked_case_indices=leaked_indices,
            detected_snippets=snippets,
            remediation="Strip all test-split cases via filter_search_cases_for_proposer.",
        )

    return LeakageAuditResult(has_leakage=False)


def partition_dataset_split[T](
    cases: list[T],
    search_ratio: float = 0.7,
    min_holdout_threshold: int = 4,
) -> tuple[list[T], list[T]]:
    """Deterministically partition cases into (search_subset, test_subset).

    Small-sample safeguard:
    When total cases < min_holdout_threshold (e.g. 1-3 cases), all are assigned
    to search to prevent artificial statistical starvation on tiny sample sizes.
    """
    if not cases:
        return ([], [])

    total = len(cases)
    if total < min_holdout_threshold:
        return (list(cases), [])

    search_count = max(1, min(total - 1, round(total * search_ratio)))
    return (list(cases[:search_count]), list(cases[search_count:]))
