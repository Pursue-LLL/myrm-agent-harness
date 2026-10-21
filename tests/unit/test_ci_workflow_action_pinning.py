"""
[POS] tests/unit/test_ci_workflow_action_pinning.py
[INPUT] pathlib, re
[OUTPUT] Unit test verifying all GitHub Actions workflow references are pinned to full commit SHAs

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

# 40-character hexadecimal SHA regex
COMMIT_SHA_REGEX: re.Pattern[str] = re.compile(r"^[0-9a-f]{40}$")
USES_REGEX: re.Pattern[str] = re.compile(r"uses:\s*([a-zA-Z0-9_\-\/]+)@([a-zA-Z0-9_\-\.]+)")


def test_all_ci_workflow_actions_are_pinned_to_sha() -> None:
    """Ensure that all GitHub Actions workflow files pin external actions to full 40-char commit SHAs.

    This guards against supply chain poisoning via mutable tags (fail-closed discipline).
    """
    repo_root = Path(__file__).resolve().parents[3]

    workflow_dirs = [
        repo_root / ".github" / "workflows",
        repo_root / "myrm-agent" / ".github" / "workflows",
        repo_root / "myrm-agent-harness" / ".github" / "workflows",
    ]

    unpinned_violations: list[str] = []

    for wdir in workflow_dirs:
        if not wdir.exists():
            continue
        for yml_path in wdir.glob("*.yml"):
            lines = yml_path.read_text(encoding="utf-8").splitlines()
            for line_no, line in enumerate(lines, start=1):
                # Ignore commented-out lines
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue

                match = USES_REGEX.search(line)
                if match:
                    action_name, ref = match.group(1), match.group(2)
                    # Ignore local composite actions
                    if action_name.startswith("./"):
                        continue

                    if not COMMIT_SHA_REGEX.match(ref):
                        unpinned_violations.append(
                            f"{yml_path.relative_to(repo_root)}:L{line_no}: {action_name}@{ref}"
                        )

    assert not unpinned_violations, (
        f"Found {len(unpinned_violations)} unpinned action(s) in CI workflows:\n"
        + "\n".join(unpinned_violations)
    )
