# [INPUT]: None
# [OUTPUT]: LivingScratchpadConfig, LivingScratchpadDocumentManager, LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite, ScratchpadBidirectionalPatcher, ScratchpadConduitInjection, ScratchpadContextConduit, ScratchpadDocument, ScratchpadPatchOp, ScratchpadScope, ScratchpadTodoItem
# [POS]: agent/context_management/living_scratchpad/__init__.py

"""Living scratchpad working memory and bidirectional context conduit package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- LivingScratchpadConfig: Configuration governing limits and token estimation.
- LivingScratchpadDocumentManager: Document persistence and Markdown checklist parser.
- LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite: Unified facade coordinating
  scratchpad co-editing, version management, and LLM context conduit injection.
- ScratchpadBidirectionalPatcher: Atomic co-editing patch mutation engine.
- ScratchpadConduitInjection: Formatted context prompt tag for injecting working memory.
- ScratchpadContextConduit: Context injection and actionable checklist prompt extractor.
- ScratchpadDocument: Immutable snapshot of scratchpad content and metadata.
- ScratchpadPatchOp: Supported atomic patch mutation operations.
- ScratchpadScope: Storage scope (SESSION_SCOPED, GLOBAL_SCOPED).
- ScratchpadTodoItem: Parsed markdown task checkbox item.

[POS]
Package entry point for living scratchpad working memory in context management.
"""

from __future__ import annotations

from .living_scratchpad_document_manager import LivingScratchpadDocumentManager
from .living_scratchpad_suite import (
    LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite,
)
from .scratchpad_bidirectional_patcher import ScratchpadBidirectionalPatcher
from .scratchpad_context_conduit import ScratchpadContextConduit
from .scratchpad_types import (
    LivingScratchpadConfig,
    ScratchpadConduitInjection,
    ScratchpadDocument,
    ScratchpadPatchOp,
    ScratchpadScope,
    ScratchpadTodoItem,
)

__all__ = [
    "LivingScratchpadConfig",
    "LivingScratchpadDocumentManager",
    "LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite",
    "ScratchpadBidirectionalPatcher",
    "ScratchpadConduitInjection",
    "ScratchpadContextConduit",
    "ScratchpadDocument",
    "ScratchpadPatchOp",
    "ScratchpadScope",
    "ScratchpadTodoItem",
]
