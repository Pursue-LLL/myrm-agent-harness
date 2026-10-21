"""Heuristic token / scope suggestions for large ARIA snapshots.

[INPUT]
- (none)

[OUTPUT]
- generate_snapshot_suggestion: Args:

[POS]
Heuristic token / scope suggestions for large ARIA snapshots.
"""


def generate_snapshot_suggestion(
    ref_count: int,
    estimated_tokens: int,
    current_scope: str,
    current_compact: bool,
    current_selector: str,
) -> str:
    """Generate a smart optimization suggestion.

    Args:
        ref_count: Current ref count.
        estimated_tokens: Estimated token count.
        current_scope: Current scope parameter.
        current_compact: Current compact parameter.
        current_selector: Current selector parameter.

    Returns:
        Suggestion string, or empty string when no suggestion applies.

    Note:
        Heuristic-based rules; finer-grained scoping can be combined with
        `browser_inspect` and `selector`.
    """
    if estimated_tokens > 2000 and not current_selector:
        saved_tokens = int(estimated_tokens * 0.7)
        return (
            f" Large page detected ({ref_count} refs, ~{estimated_tokens} tokens)\n"
            f"→ Recommended: Use browser_inspect() to get precise selector (saves ~70%, ~{saved_tokens} tokens)\n"
            f"→ Quick fix: scope='interactive' (saves ~60%) or compact=True (saves ~30%)"
        )

    if ref_count > 200 and current_scope != "interactive":
        saved_tokens = int(estimated_tokens * 0.6)
        return (
            f" Many elements detected ({ref_count} refs, ~{estimated_tokens} tokens)\n"
            f"→ Recommended: scope='interactive' (saves ~60%, ~{saved_tokens} tokens)\n"
            f"→ Alternative: compact=True (saves ~30%) or use selector for specific region"
        )

    if ref_count > 200 and not current_compact:
        saved_tokens = int(estimated_tokens * 0.3)
        return f" Optimization tip: compact=True can save ~30% tokens (~{saved_tokens} tokens, single-line format)"

    return ""
