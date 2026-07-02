"""Completion guard checklist generation and verification command classification.

[INPUT]
- agent.security.guards.loop_guard_types::CallRecord, ToolGroup, SuccessLevel (POS: loop guard types)

[OUTPUT]
- classify_verification(): detect verification commands in bash tool args
- build_checklist(): generate task-aware verification checklist from CallRecords

[POS]
Verification command classification and task-aware checklist generation for CompletionGuard.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    CallRecord,
    SuccessLevel,
    ToolGroup,
    VerificationCategory,
    get_tool_group,
)

logger = logging.getLogger(__name__)

_VERIFICATION_PATTERNS: dict[str, VerificationCategory] = {
    "pytest": VerificationCategory.TEST,
    "python -m pytest": VerificationCategory.TEST,
    "npm test": VerificationCategory.TEST,
    "npm run test": VerificationCategory.TEST,
    "npx jest": VerificationCategory.TEST,
    "yarn test": VerificationCategory.TEST,
    "bun test": VerificationCategory.TEST,
    "pnpm test": VerificationCategory.TEST,
    "pnpm run test": VerificationCategory.TEST,
    "deno test": VerificationCategory.TEST,
    "cargo test": VerificationCategory.TEST,
    "go test": VerificationCategory.TEST,
    "dotnet test": VerificationCategory.TEST,
    "mvn test": VerificationCategory.TEST,
    "gradle test": VerificationCategory.TEST,
    "vitest": VerificationCategory.TEST,
    "unittest": VerificationCategory.TEST,
    "python": VerificationCategory.TEST,
    "node": VerificationCategory.TEST,
    "ts-node": VerificationCategory.TEST,
    "bun run": VerificationCategory.TEST,
    "deno run": VerificationCategory.TEST,
    "go run": VerificationCategory.TEST,
    "ruby": VerificationCategory.TEST,
    "php": VerificationCategory.TEST,
    "gcc": VerificationCategory.BUILD,
    "g++": VerificationCategory.BUILD,
    "javac": VerificationCategory.BUILD,
    "java": VerificationCategory.TEST,
    "ruff check": VerificationCategory.LINT,
    "ruff format": VerificationCategory.LINT,
    "eslint": VerificationCategory.LINT,
    "flake8": VerificationCategory.LINT,
    "pylint": VerificationCategory.LINT,
    "biome check": VerificationCategory.LINT,
    "biome lint": VerificationCategory.LINT,
    "prettier": VerificationCategory.LINT,
    "black": VerificationCategory.LINT,
    "isort": VerificationCategory.LINT,
    "clippy": VerificationCategory.LINT,
    "golangci-lint": VerificationCategory.LINT,
    "mypy": VerificationCategory.TYPECHECK,
    "pyright": VerificationCategory.TYPECHECK,
    "tsc": VerificationCategory.TYPECHECK,
    "npx tsc": VerificationCategory.TYPECHECK,
    "cargo build": VerificationCategory.BUILD,
    "npm run build": VerificationCategory.BUILD,
    "yarn build": VerificationCategory.BUILD,
    "pnpm run build": VerificationCategory.BUILD,
    "bun run build": VerificationCategory.BUILD,
    "make build": VerificationCategory.BUILD,
    "go build": VerificationCategory.BUILD,
    "dotnet build": VerificationCategory.BUILD,
    "gradle build": VerificationCategory.BUILD,
}


def _is_command_at_boundary(cmd: str, pattern: str) -> bool:
    """Check if pattern matches at a word boundary (followed by space or end-of-string)."""
    return cmd == pattern or cmd.startswith(pattern + " ")


def classify_verification(tool_args: dict[str, object]) -> VerificationCategory | None:
    """Detect if a bash command is a verification action (test/lint/typecheck/build).

    Uses word-boundary matching to minimise false positives. For example,
    ``pip install pytest`` will NOT match because ``pytest`` does not appear
    at a command boundary, and ``npm test-helper`` will NOT match ``npm test``
    because the pattern is followed by ``-`` instead of a space or end-of-string.
    """
    command = str(tool_args.get("command", "")).strip()
    if not command:
        return None
    cmd_lower = command.lower()
    for pattern, category in sorted(_VERIFICATION_PATTERNS.items(), key=lambda x: len(x[0]), reverse=True):
        if _is_command_at_boundary(cmd_lower, pattern):
            return category
        for sep in (" && ", "; "):
            idx = cmd_lower.find(sep + pattern)
            if idx >= 0:
                tail = cmd_lower[idx + len(sep) :]
                if _is_command_at_boundary(tail, pattern):
                    return category
    return None


def reset_completion_guard() -> None:
    """Reset guard state — call at the start of each agent run."""
    global _rejection_count
    _rejection_count = 0


def build_checklist(records: list[CallRecord], workspace_root: str | None = None) -> tuple[str, bool]:
    """Generate a verification checklist from LoopGuard CallRecords.

    Groups tool calls by semantic category and produces targeted
    verification items based on what the Agent actually did.

    Internal tool records (``_``-prefixed) are filtered out first.
    ``has_critical_errors`` is True only when code files were modified
    without passing verification — this drives the CRITICAL blocking path.

    Returns:
        Tuple of (checklist_string, has_critical_errors)
    """
    records = [r for r in records if not r.tool_name.startswith("_")]

    groups: dict[ToolGroup, list[CallRecord]] = {}
    for rec in records:
        grp = get_tool_group(rec.tool_name)
        groups.setdefault(grp, []).append(rec)

    verifications = [r for r in records if r.verification_type is not None]
    failed_verifications = [r for r in verifications if r.success_level == SuccessLevel.FAILURE]

    items: list[str] = []
    has_critical_errors = False
    has_writes = ToolGroup.WRITE in groups

    if has_writes:
        write_records = groups[ToolGroup.WRITE]
        write_tools = {r.tool_name for r in write_records}

        # Check if any written file is a code file that requires testing
        has_code_writes = False
        code_extensions = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".rs",
            ".go",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".cs",
            ".php",
            ".rb",
            ".swift",
        }
        for rec in write_records:
            path = str(rec.args.get("path", "")).lower()
            if any(path.endswith(ext) for ext in code_extensions):
                has_code_writes = True
                break

        if not verifications:
            if has_code_writes:
                has_critical_errors = True
                items.append(
                    f"CRITICAL: Code files were modified ({', '.join(sorted(write_tools))}) but NO verification "
                    "(tests, lint, type-check) was executed. You MUST run relevant checks before finishing."
                )
            else:
                items.append(
                    f" Files were modified ({', '.join(sorted(write_tools))}) but NO verification was executed. "
                    "If these are text/data files, please manually confirm they meet the requirements."
                )
        elif failed_verifications:
            has_critical_errors = True
            failed_types = {r.verification_type.value for r in failed_verifications if r.verification_type}
            items.append(
                f"CRITICAL: Verification failed for: {', '.join(sorted(failed_types))}. You MUST fix failing checks before finishing."
            )
        elif all(r.success_level == SuccessLevel.EMPTY_OK for r in verifications):
            has_critical_errors = True
            trivial_types = {r.verification_type.value for r in verifications if r.verification_type}
            items.append(
                f"CRITICAL: Verification ({', '.join(sorted(trivial_types))}) ran but produced "
                "no meaningful results (0 tests executed / all skipped). "
                "You MUST ensure tests actually run before finishing."
            )
        else:
            verified_types = {r.verification_type.value for r in verifications if r.verification_type}
            items.append(
                f"File modifications ({', '.join(sorted(write_tools))}) verified via "
                f"{', '.join(sorted(verified_types))} — confirm results match expectations."
            )

    if ToolGroup.BROWSER in groups:
        browser_tools = {r.tool_name for r in groups[ToolGroup.BROWSER]}
        items.append(
            f"Verify browser interactions ({', '.join(sorted(browser_tools))}) "
            "produced expected results — take a snapshot to confirm page state."
        )
    elif has_writes:
        frontend_render_exts: frozenset[str] = frozenset(
            {".tsx", ".jsx", ".vue", ".svelte", ".astro", ".css", ".scss", ".less", ".html"}
        )
        non_render_path_segments: frozenset[str] = frozenset(
            {
                "test",
                "tests",
                "spec",
                "specs",
                "__tests__",
                "__test__",
                "store",
                "stores",
                "service",
                "services",
                "util",
                "utils",
                "hook",
                "hooks",
                "api",
                "types",
                "constants",
                "schemas",
                "mocks",
                "mock",
            }
        )
        non_render_filename_patterns: tuple[str, ...] = (
            ".test.",
            ".spec.",
            ".d.ts",
            ".config.",
            ".stories.",
        )

        def _is_non_render_path(p: str) -> bool:
            segments = set(p.replace("\\", "/").split("/"))
            if segments & non_render_path_segments:
                return True
            filename = p.rsplit("/", 1)[-1]
            return any(pat in filename for pat in non_render_filename_patterns)

        has_render_file_writes = any(
            any(path_lower.endswith(ext) for ext in frontend_render_exts) and not _is_non_render_path(path_lower)
            for rec in groups[ToolGroup.WRITE]
            if (path_lower := str(rec.args.get("path", "")).lower())
        )
        if has_render_file_writes:
            items.append(
                "WARNING: Frontend rendering files were modified but NO browser "
                "verification was performed. Consider using browser tools to "
                "visually confirm the changes render correctly."
            )

    reported_failures: set[str] = set()

    if ToolGroup.EXECUTE in groups:
        exec_tools = {r.tool_name for r in groups[ToolGroup.EXECUTE]}
        failures = [r for r in groups[ToolGroup.EXECUTE] if r.success_level == SuccessLevel.FAILURE]
        item = f"Verify execution results from {', '.join(sorted(exec_tools))} match expectations."
        if failures:
            reported_failures.update(r.tool_name for r in failures)
            if has_writes:
                has_critical_errors = True
                item = f"CRITICAL: {len(failures)} execution(s) failed in {', '.join(sorted(exec_tools))}. You MUST resolve them."
            else:
                item = f"WARNING: {len(failures)} execution(s) had failures in {', '.join(sorted(exec_tools))}. Review if they affect the answer."
        items.append(item)

    other_failures = [
        r for r in records if r.success_level == SuccessLevel.FAILURE and r.tool_name not in reported_failures
    ]
    if other_failures:
        failed_tools = {r.tool_name for r in other_failures}
        if has_writes:
            has_critical_errors = True
            items.append(
                f"CRITICAL: Address {len(other_failures)} unresolved failure(s) in: {', '.join(sorted(failed_tools))}."
            )
        else:
            items.append(
                f"WARNING: {len(other_failures)} failure(s) in {', '.join(sorted(failed_tools))}. Review if they affect the answer."
            )

    if not items:
        items.append("Confirm the response fully addresses the user's request.")

    lines = ["Before providing your final answer, verify the following:"]

    # Check for incomplete todo items
    if workspace_root:
        try:
            from myrm_agent_harness.agent.meta_tools.progress.storage import read_todos_sync_from_workspace

            store = read_todos_sync_from_workspace(workspace_root)
            if store:
                incomplete = store.incomplete_todos()
                if incomplete:
                    if has_writes:
                        has_critical_errors = True
                        lines.append("  CRITICAL: You have incomplete todos in your task list!")
                    else:
                        lines.append("  WARNING: You have incomplete todos in your task list.")
                    for item in incomplete:
                        lines.append(f" - Todo {item.id}: {item.content} (Status: {item.status.value})")
                    if has_writes:
                        lines.append(
                            " You MUST complete these todos and call `todo_write(merge=true)` before finishing."
                        )
                    else:
                        lines.append(" Review if remaining todos are still needed for your answer.")
                    lines.append("")
        except Exception as e:
            logger.warning("[CompletionGuard] Failed to load todos for checklist: %s", e)

    for i, item in enumerate(items, 1):
        lines.append(f" {i}. {item}")
    lines.append("")
    lines.append("RULES:")
    lines.append('- "Looks correct" is NOT verification — run the actual check.')
    lines.append("- Tests you wrote need independent verification — confirm they catch real bugs.")
    lines.append('- "Should work" is NOT "verified" — execute and confirm.')
    lines.append("- If you cannot verify something, state what and why explicitly.")
    lines.append("")

    if has_critical_errors:
        lines.append(" STATUS: REJECTED. You have CRITICAL errors. You CANNOT finish the task until they are resolved.")
    else:
        lines.append(
            " STATUS: WARNINGS ONLY. If all checks pass, provide your final answer. If issues found, fix them first."
        )

    return "\n".join(lines), has_critical_errors


