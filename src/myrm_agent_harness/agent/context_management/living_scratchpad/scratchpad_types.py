# [INPUT]: None
# [OUTPUT]: LivingScratchpadConfig, ScratchpadConduitInjection, ScratchpadDocument, ScratchpadPatchOp, ScratchpadScope, ScratchpadTodoItem
# [POS]: agent/context_management/living_scratchpad/scratchpad_types.py

"""Domain models and contracts for living scratchpad working memory and bidirectional context conduit.

[INPUT]
- None (Self-contained domain models and contracts).

[OUTPUT]
- ScratchpadScope: Storage scope (SESSION_SCOPED, GLOBAL_SCOPED).
- ScratchpadPatchOp: Supported patch operations for human/AI co-editing (REPLACE, APPEND, TOGGLE_TODO, LINE_PATCH).
- ScratchpadTodoItem: Parsed markdown todo checklist item with line number and status.
- ScratchpadDocument: Immutable snapshot of scratchpad text, version, and parsed todos.
- ScratchpadConduitInjection: Formatted context prompt tag for injecting working memory into LLM turns.
- LivingScratchpadConfig: Configuration governing max characters, injection headers, and token estimation.

[POS]
Domain contract layer for living scratchpad working memory in context management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class ScratchpadScope(str, Enum):
    """Storage and isolation scope of the scratchpad."""

    SESSION_SCOPED = "session_scoped"  # Bound to a specific active conversation session
    GLOBAL_SCOPED = "global_scoped"    # Shared across all user workspace conversations


class ScratchpadPatchOp(str, Enum):
    """Atomic patch mutation operations supported by bidirectional co-editing."""

    REPLACE = "replace"          # Full document content overwrite
    APPEND = "append"            # Append new lines or checklist items to the end
    TOGGLE_TODO = "toggle_todo"  # Toggle completion status of a todo at line or index
    LINE_PATCH = "line_patch"    # Replace a specific line or slice of lines


@dataclass(frozen=True)
class ScratchpadTodoItem:
    """Represents a parsed Markdown task checkbox (- [ ] or - [x])."""

    text: str
    is_completed: bool
    line_number: int  # 1-indexed


@dataclass(frozen=True)
class ScratchpadDocument:
    """Immutable representation of scratchpad content and metadata."""

    scratchpad_id: str
    scope: ScratchpadScope
    session_id: str | None
    title: str
    content: str
    version: int
    updated_at: float
    todos: tuple[ScratchpadTodoItem, ...] = field(default_factory=tuple)

    @property
    def completed_todos_count(self) -> int:
        return sum(1 for t in self.todos if t.is_completed)

    @property
    def pending_todos_count(self) -> int:
        return sum(1 for t in self.todos if not t.is_completed)

    @property
    def has_pending_todos(self) -> bool:
        return self.pending_todos_count > 0


@dataclass(frozen=True)
class ScratchpadConduitInjection:
    """Serialized context block ready for system prompt or turn tail injection."""

    tag_text: str
    version: int
    estimated_tokens: int
    has_pending_todos: bool
    total_todos: int
    completed_todos: int


@dataclass(frozen=True)
class LivingScratchpadConfig:
    """Config controlling limits, token estimation ratios, and auto-injection defaults."""

    max_content_chars: int = 16384
    token_char_ratio: float = 4.0
    auto_inject_into_context: bool = True
    default_title: str = "Active Working Scratchpad"
