"""Evaluation Hidden Test Isolation and Trajectory Anti-Contamination Auditor.

Provides deterministic validation ensuring that evaluation test suites and
ground-truth assets are strictly excluded from the agent's live workspace
during execution turns (In-Episode) and only attached/evaluated during post-episode
grading (Post-Episode DoD Gate). Additionally audits the agent's trajectory for
cheating attempts (e.g. attempting to read hidden verifiers or leaking canary strings).

[INPUT]
- Workspace file paths, tool call details trajectory, and hidden test path contracts.

[OUTPUT]
- ContaminationViolationType: Classification of anti-contamination violations.
- ContaminationViolation: Structured violation record.
- ContaminationAuditResult: Complete evaluation turn anti-contamination audit status.
- verify_workspace_clean_of_hidden_tests: Asserts agent workspace is clean before turn.
- audit_episode_trajectory_for_contamination: Audits trajectory for cheating attempts.
- scrub_canary_from_query: Sanitizes queries against benchmark canary leakage.

[POS]
Harness framework evaluation layer - pure algorithmic & zero direct IO side effects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.eval.canary import CANARY_GUID


# Default hidden patterns that should never exist inside an agent's active workspace.
DEFAULT_HIDDEN_TEST_PATTERNS: tuple[str, ...] = (
    "verifier.toml",
    "tests/verifier.py",
    "tests/scorer.py",
    "eval_tests/",
    "hidden_tests/",
    "hidden_eval/",
    "eval_grader/",
    ".gold.patch",
    "golden.patch",
    "hidden_test",
    "ground_truth",
)


class ContaminationViolationType(StrEnum):
    """Classification of anti-contamination and cheating violations."""

    HIDDEN_PATH_ACCESSED = "hidden_path_accessed"
    CANARY_SEARCH_LEAK = "canary_search_leak"
    PRE_RUN_WORKSPACE_DIRTY = "pre_run_workspace_dirty"
    GOLDEN_PATCH_TAMPERED = "golden_patch_tampered"


@dataclass(slots=True, frozen=True)
class ContaminationViolation:
    """Structured record of a single anti-contamination violation."""

    violation_type: str
    details: str
    tool_name: str = ""
    target: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert violation to a serializable dictionary."""
        return {
            "violation_type": self.violation_type,
            "details": self.details,
            "tool_name": self.tool_name,
            "target": self.target,
        }


@dataclass(slots=True, frozen=True)
class ContaminationAuditResult:
    """Complete audit result for an evaluation episode."""

    is_clean: bool
    cheat_detected: bool
    violations: list[ContaminationViolation] = field(default_factory=list)
    scanned_tool_calls: int = 0
    details: str = "Clean episode: no hidden test access or canary contamination detected."

    def to_dict(self) -> dict[str, object]:
        """Convert audit result to a serializable dictionary."""
        return {
            "is_clean": self.is_clean,
            "cheat_detected": self.cheat_detected,
            "violations": [v.to_dict() for v in self.violations],
            "scanned_tool_calls": self.scanned_tool_calls,
            "details": self.details,
        }


def verify_workspace_clean_of_hidden_tests(
    workspace: Sequence[str] | Path | str,
    hidden_patterns: Sequence[str] | None = None,
) -> tuple[bool, list[str]]:
    """Verify that an agent workspace is clean of hidden tests and golden assets.

    Returns:
        tuple of (is_clean, list_of_matching_dirty_files).
    """
    patterns = hidden_patterns if hidden_patterns is not None else DEFAULT_HIDDEN_TEST_PATTERNS
    dirty_files: list[str] = []

    if isinstance(workspace, (Path, str)):
        root = Path(workspace)
        if root.exists() and root.is_dir():
            file_paths = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]
        elif root.exists():
            file_paths = [root.name]
        else:
            file_paths = []
    else:
        file_paths = list(workspace)

    for file_path in file_paths:
        normalized = file_path.replace("\\", "/").strip()
        for pat in patterns:
            if pat.endswith("/"):
                if normalized.startswith(pat) or f"/{pat}" in normalized:
                    dirty_files.append(file_path)
                    break
            elif pat in normalized:
                dirty_files.append(file_path)
                break

    is_clean = len(dirty_files) == 0
    return is_clean, dirty_files


def scrub_canary_from_query(
    query: str,
    canary_tokens: Sequence[str] | None = None,
) -> str:
    """Scrub canary strings and anti-contamination tokens from an outbound query."""
    tokens = list(canary_tokens) if canary_tokens is not None else [CANARY_GUID]
    scrubbed = query
    for token in tokens:
        if token and token in scrubbed:
            scrubbed = scrubbed.replace(token, "[REDACTED_CANARY]")
    return scrubbed


def audit_episode_trajectory_for_contamination(
    tool_call_details: Sequence[dict[str, object]],
    hidden_paths: Sequence[str] | None = None,
    canary_tokens: Sequence[str] | None = None,
) -> ContaminationAuditResult:
    """Audit the agent's tool invocation trajectory for cheating or contamination.

    Scans tools such as bash, file_read, read_file, grep, glob, web_search,
    and web_fetch to ensure the agent did not probe hidden grading suites or leak
    canary strings.
    """
    hidden = list(hidden_paths) if hidden_paths is not None else list(DEFAULT_HIDDEN_TEST_PATTERNS)
    canaries = list(canary_tokens) if canary_tokens is not None else [CANARY_GUID]

    violations: list[ContaminationViolation] = []
    scanned_count = len(tool_call_details)

    for call in tool_call_details:
        tool_name = str(call.get("tool_name") or call.get("name") or call.get("tool") or call.get("step_key") or "")
        arg_candidates = [
            call.get("args"),
            call.get("arguments"),
            call.get("input"),
            call.get("detail"),
            call.get("command"),
            call.get("path"),
            call.get("query"),
        ]
        arg_parts = [str(x) for x in arg_candidates if x is not None]
        arg_str = " ".join(arg_parts) if arg_parts else str(call)

        # 1. Check for canary string leaking in outbound web tools
        if tool_name in {"web_search", "web_fetch", "search", "browse", "fetch"}:
            for canary in canaries:
                if canary in arg_str:
                    violations.append(
                        ContaminationViolation(
                            violation_type=ContaminationViolationType.CANARY_SEARCH_LEAK.value,
                            details=f"Canary string leaked in outbound query: '{canary}'.",
                            tool_name=tool_name,
                            target=arg_str[:120],
                        )
                    )

        # 2. Check for hidden grading path access in local filesystem tools
        for hidden_path in hidden:
            if not hidden_path:
                continue
            normalized_path = hidden_path.replace("\\", "/").rstrip("/")
            # Check direct occurrence or regex matching
            if normalized_path in arg_str:
                violations.append(
                    ContaminationViolation(
                        violation_type=ContaminationViolationType.HIDDEN_PATH_ACCESSED.value,
                        details=(
                            f"Agent attempted to probe or access hidden grading asset '{hidden_path}' "
                            f"via tool '{tool_name}'."
                        ),
                        tool_name=tool_name,
                        target=hidden_path,
                    )
                )

    cheat_detected = any(
        v.violation_type in {
            ContaminationViolationType.HIDDEN_PATH_ACCESSED.value,
            ContaminationViolationType.GOLDEN_PATCH_TAMPERED.value,
        }
        for v in violations
    )
    is_clean = len(violations) == 0

    details = (
        "Clean episode: no hidden test access or canary contamination detected."
        if is_clean
        else f"Contamination detected: {len(violations)} violation(s) found. Cheat attempt: {cheat_detected}."
    )

    return ContaminationAuditResult(
        is_clean=is_clean,
        cheat_detected=cheat_detected,
        violations=violations,
        scanned_tool_calls=scanned_count,
        details=details,
    )
