"""Context Budget Guard — prevent context window overflow from tool results.

Four layers of protection:
1. Single tool result size limit (persist or truncate oversized results)
2. Session total context budget tracking (cumulative token estimation)
3. Predictive overflow detection (warn before overflow, not after)
4. Graceful degradation (disk-persist → truncate fallback chain)

[INPUT]
- text_utils::smart_truncate (POS: Head+Tail truncation with intelligent tail detection)

[OUTPUT]
- BudgetVerdict: persisted / truncated / warning / ok (with details)
- ContextBudgetGuard: session-scoped instance tracking budget usage

[POS]
Session-level guard. Integrated into tool_interceptor_middleware at
the post-call stage, after tool execution but before result validation.
"""

from __future__ import annotations

import contextlib
import logging
import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.utils.text_utils import smart_truncate

logger = logging.getLogger(__name__)

_PERSIST_NOTICE = (
    "\n\n[FULL RESULT SAVED: {path} ({original} chars, {lines} lines)]\n"
    "[Read the file at the path above to access the complete content]\n"
)

_PREVIEW_CHARS = 500

# Tools whose output must NOT be truncated at Layer 1 (single-result limit).
# Truncating file read results causes a "read → truncate → persist → re-read"
# loop: the model reads the persisted file, which gets truncated again, etc.
# These tools' large outputs are handled by downstream context management
# (CompressProcessor → SummarizeProcessor) instead.
_LAYER1_EXEMPT_TOOLS: frozenset[str] = frozenset(
    {
        "file_read_tool",
        "file_edit_tool",
    }
)


class BudgetAction(StrEnum):
    """Verdict action for context budget check."""

    OK = "ok"
    TRUNCATED = "truncated"
    PERSISTED = "persisted"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class BudgetVerdict:
    """Result of context budget check."""

    action: BudgetAction
    content: str
    reason: str
    budget_used_pct: float
    persisted_path: str | None = None


def _estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English/code."""
    return max(1, len(text) // 4)


def _build_persist_summary(content: str, file_path: str) -> str:
    """Build a summary with head/tail preview and file path."""
    line_count = content.count("\n") + 1
    notice = _PERSIST_NOTICE.format(path=file_path, original=len(content), lines=line_count)
    head = content[:_PREVIEW_CHARS]
    tail = content[-_PREVIEW_CHARS:] if len(content) > _PREVIEW_CHARS * 2 else ""
    if tail:
        return f"{head}\n...{notice}\n...{tail}"
    return f"{head}{notice}"


class ContextBudgetGuard:
    """Session-scoped context budget tracker.

    Tracks cumulative token usage from tool results and enforces
    per-result and total budget limits. Oversized results are persisted
    to disk when persist_dir is configured, falling back to truncation.

    Args:
        max_result_chars: max characters for a single tool result (default 100_000)
        total_budget_tokens: total context budget in estimated tokens (default 100_000)
        warning_pct: percentage of budget used before warning (default 0.80)
        hard_limit_pct: percentage of budget used before forced truncation (default 0.95)
        min_retained_chars: minimum characters to retain after truncation (default 200)
        persist_dir: directory for persisting oversized results (None = truncate-only)
    """

    def __init__(
        self,
        *,
        max_result_chars: int = 100_000,
        total_budget_tokens: int = 100_000,
        warning_pct: float = 0.80,
        hard_limit_pct: float = 0.95,
        min_retained_chars: int = 200,
        persist_dir: Path | None = None,
    ) -> None:
        self._max_result_chars = max_result_chars
        self._total_budget_tokens = total_budget_tokens
        self._warning_pct = warning_pct
        self._hard_limit_pct = hard_limit_pct
        self._min_retained_chars = min_retained_chars
        self._persist_dir = persist_dir
        self._used_tokens = 0
        self._persisted_files: list[Path] = []

    @property
    def used_tokens(self) -> int:
        return self._used_tokens

    @property
    def budget_used_pct(self) -> float:
        if self._total_budget_tokens <= 0:
            return 1.0
        return self._used_tokens / self._total_budget_tokens

    @property
    def persisted_files(self) -> list[Path]:
        return list(self._persisted_files)

    def _try_persist(self, content: str, tool_name: str) -> tuple[str, str] | None:
        """Try to persist content to disk. Returns (summary, file_path) or None."""
        if self._persist_dir is None:
            return None
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            short_id = uuid.uuid4().hex[:8]
            safe_name = re.sub(r"[^\w]", "_", tool_name)
            file_path = self._persist_dir / f"{safe_name}_{short_id}.txt"
            file_path.write_text(content, encoding="utf-8")
            self._persisted_files.append(file_path)
            summary = _build_persist_summary(content, str(file_path))
            return summary, str(file_path)
        except OSError:
            logger.warning("Failed to persist tool result to disk, falling back to truncation")
            return None

    def check_and_truncate(self, content: str, tool_name: str) -> BudgetVerdict:
        """Check a tool result against budget limits.

        When a result exceeds max_result_chars:
        - If persist_dir is configured: save full result to disk, return summary
        - Otherwise: truncate with head+tail preservation

        This is the main entry point called from middleware post-call.
        """
        original_len = len(content)
        result_content = content
        persisted_path: str | None = None
        was_persisted = False

        # Layer 1: single result size limit — persist or truncate.
        # File read/edit tools are exempt: truncating their output causes a
        # "read → truncate → persist → re-read" loop. Their large outputs
        # are handled by downstream context management instead.
        skip_layer1 = tool_name in _LAYER1_EXEMPT_TOOLS
        if not skip_layer1 and original_len > self._max_result_chars:
            persist_result = self._try_persist(content, tool_name)
            if persist_result is not None:
                result_content, persisted_path = persist_result
                was_persisted = True
            else:
                result_content = smart_truncate(content, self._max_result_chars)

        # Layer 3: predictive overflow — if adding this result would exceed hard limit,
        # truncate further to fit within remaining budget
        if not was_persisted:
            result_tokens = _estimate_tokens(result_content)
            projected_pct = (self._used_tokens + result_tokens) / max(1, self._total_budget_tokens)

            if projected_pct >= self._hard_limit_pct:
                remaining_tokens = max(
                    max(1, self._min_retained_chars // 4),
                    int(self._total_budget_tokens * (1.0 - self.budget_used_pct) * 0.8),
                )
                remaining_chars = remaining_tokens * 4
                if len(result_content) > remaining_chars:
                    result_content = smart_truncate(result_content, remaining_chars)

        # Update cumulative budget
        actual_tokens = _estimate_tokens(result_content)
        self._used_tokens += actual_tokens
        current_pct = self.budget_used_pct

        # Determine verdict
        if was_persisted:
            return BudgetVerdict(
                action=BudgetAction.PERSISTED,
                content=result_content,
                reason=(
                    f"Tool '{tool_name}' result persisted to disk: "
                    f"{original_len} chars → {persisted_path} "
                    f"(budget: {current_pct:.0%})"
                ),
                budget_used_pct=current_pct,
                persisted_path=persisted_path,
            )

        if len(result_content) < original_len:
            return BudgetVerdict(
                action=BudgetAction.TRUNCATED,
                content=result_content,
                reason=(
                    f"Tool '{tool_name}' result truncated: "
                    f"{original_len} → {len(result_content)} chars "
                    f"(budget: {current_pct:.0%})"
                ),
                budget_used_pct=current_pct,
            )

        # Layer 2: warning threshold
        if current_pct >= self._warning_pct:
            return BudgetVerdict(
                action=BudgetAction.WARNING,
                content=result_content,
                reason=(f"Context budget at {current_pct:.0%} after '{tool_name}' ({actual_tokens} tokens added)"),
                budget_used_pct=current_pct,
            )

        return BudgetVerdict(action=BudgetAction.OK, content=result_content, reason="", budget_used_pct=current_pct)

    def reset(self) -> None:
        """Clear budget tracking and persisted files."""
        self._used_tokens = 0
        for path in self._persisted_files:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        self._persisted_files.clear()


_budget_guard_var: ContextVar[ContextBudgetGuard] = ContextVar("context_budget_guard")


def _resolve_persist_dir() -> Path | None:
    """Resolve persist_dir from current session context.

    Uses the session-aware evicted directory when a chat_id is available,
    ensuring persisted tool results are cleaned up with the session.
    Falls back to a temporary directory when no session context exists.
    """
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import get_current_chat_id
        from myrm_agent_harness.runtime.execution_paths import CONTEXT_ROOT

        chat_id = get_current_chat_id()
        if chat_id:
            safe_id = re.sub(r"[^\w\-]", "_", chat_id)
            return Path(f"{CONTEXT_ROOT}/{safe_id}/evicted")

        import tempfile

        return Path(tempfile.gettempdir()) / "myrm-budget-persist"
    except Exception:
        return None


def get_context_budget_guard() -> ContextBudgetGuard:
    """Get or create the session-scoped ContextBudgetGuard.

    On first access, automatically resolves persist_dir from the current
    session context so that oversized tool results are persisted to disk
    rather than silently truncated.
    """
    try:
        return _budget_guard_var.get()
    except LookupError:
        persist_dir = _resolve_persist_dir()
        guard = ContextBudgetGuard(persist_dir=persist_dir)
        _budget_guard_var.set(guard)
        return guard


def set_context_budget_guard(guard: ContextBudgetGuard) -> None:
    """Set a custom ContextBudgetGuard for the current session.

    Call before any tool execution to configure custom budget limits.
    """
    _budget_guard_var.set(guard)


def reset_context_budget() -> None:
    """Reset the context budget for a new session."""
    with contextlib.suppress(LookupError):
        _budget_guard_var.get().reset()
