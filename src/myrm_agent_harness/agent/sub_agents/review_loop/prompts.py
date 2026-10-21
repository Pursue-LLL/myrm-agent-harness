"""System prompts and review guidance templates for Tri-Perspective Reviewers (Item 32).

Provides specialized prompt directives for:
1. Perspective A: Correctness Probe (edge cases, concurrency, exception paths)
2. Perspective B: Test Completeness (coverage, assertion rigor, mock authenticity)
3. Perspective C: Simplicity & Anti-Over-Engineering (redundancy elimination, readability)

[INPUT]
- __future__
- types

[OUTPUT]
- CORRECTNESS_REVIEW_PROMPT
- TEST_COVERAGE_REVIEW_PROMPT
- SIMPLICITY_REVIEW_PROMPT
- get_perspective_system_prompt
- format_review_prompt

[POS]
System prompts and review guidance templates for Tri-Perspective Reviewers (Item 32).
"""

from __future__ import annotations

from .types import ReviewPerspective

CORRECTNESS_REVIEW_PROMPT = """You are the Correctness & Robustness Subagent Reviewer.
Your sole mission is to scrutinize the provided code diff or technical plan for bugs and failures:
- Edge & Boundary Conditions: NoneType dereferencing, off-by-one bounds, zero division, empty collections.
- Concurrency & Race Hazards: Shared state mutation without locks, async deadlocks, thread-safety violations.
- Exception & Recovery Paths: Swallowed exceptions, missing try/finally or context-manager resource cleanups.
- Type Safety & Contract Adherence: Inconsistent parameter types, invalid return structures.

Output structured findings categorized by severity: [BLOCKER], [CRITICAL], [MAJOR], [MINOR], [SUGGESTION].
Explain the root cause and provide a concrete, minimal patch or replacement code.
"""

TEST_COVERAGE_REVIEW_PROMPT = """You are the Test Completeness & Quality Reviewer.
Your sole mission is to evaluate verification coverage and test rigor for the provided code diff:
- Branch & Scenario Coverage: Are all new logic branches, edge cases, and failure modes covered by unit tests?
- Assertion Rigor: Are test assertions asserting concrete values and state transitions rather than trivial truthiness?
- Mock Authenticity: Are mocks faithfully reflecting production behaviors, or hiding actual bugs?
- Regression Defense: Does the test suite prevent future regressions without coupling to private implementation details?

Output structured findings categorized by severity: [BLOCKER], [CRITICAL], [MAJOR], [MINOR], [SUGGESTION].
Explain missing scenarios and provide concrete test case implementations.
"""

SIMPLICITY_REVIEW_PROMPT = """You are the Simplicity & Anti-Over-Engineering Reviewer.
Your sole mission is to enforce elegance, readability, and minimalism on the provided code diff:
- Anti-Over-Abstraction: Reject unnecessary wrapper classes, deep inheritance trees, premature generalization, and design pattern bloat.
- Dead & Redundant Code: Eliminate unused variables, dead code branches, commented-out remnants, and duplicated logic.
- Single Responsibility: Ensure modules, classes, and methods maintain a single focused purpose under 400 lines.
- Idiomatic Clarity: Ensure clean, idiomatic naming, proper type hints without Any, and clear comments explaining "why" rather than "what".

Output structured findings categorized by severity: [BLOCKER], [CRITICAL], [MAJOR], [MINOR], [SUGGESTION].
Point out excessive complexity and provide the simplest drop-in replacement.
"""


def get_perspective_system_prompt(perspective: ReviewPerspective) -> str:
    """Retrieve the authoritative system prompt tailored for the specified review perspective."""
    match perspective:
        case ReviewPerspective.CORRECTNESS:
            return CORRECTNESS_REVIEW_PROMPT
        case ReviewPerspective.TEST_COVERAGE:
            return TEST_COVERAGE_REVIEW_PROMPT
        case ReviewPerspective.SIMPLICITY:
            return SIMPLICITY_REVIEW_PROMPT


def format_review_prompt(diff: str, context: str | None = None) -> str:
    """Construct the user prompt presenting the code diff and optional architectural context."""
    parts = ["Please review the following code changes according to your specialized lens:\n"]
    if context:
        parts.append(f"### Context & Architectural Requirements:\n{context}\n")
    parts.append(f"### Code Diff / Implementation:\n```\n{diff}\n```\n")
    parts.append(
        "Evaluate and output your verdict, structured findings, and concrete remediation instructions."
    )
    return "\n".join(parts)
