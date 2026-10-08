"""Bidirectional scratchpad patcher executing atomic patch mutations for human and agent co-editing.

[INPUT]
- LivingScratchpadDocumentManager, ScratchpadDocument, ScratchpadPatchOp: Domain types.

[OUTPUT]
- ScratchpadBidirectionalPatcher: Executes replace, append, line-patch, and todo-toggle mutations.

[POS]
Co-editing mutation and atomic patch resolution layer for living scratchpads.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from .living_scratchpad_document_manager import LivingScratchpadDocumentManager
from .scratchpad_types import ScratchpadDocument, ScratchpadPatchOp


class ScratchpadBidirectionalPatcher:
    """Applies atomic incremental patches and manages optimistic concurrency versions."""

    def __init__(self, doc_manager: LivingScratchpadDocumentManager) -> None:
        self._doc_manager = doc_manager

    def apply_patch(
        self,
        doc: ScratchpadDocument,
        op: ScratchpadPatchOp,
        payload: str,
        target_line: int | None = None,
        expected_version: int | None = None,
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Applies a patch mutation to the document, asserting version match if specified."""
        if expected_version is not None and doc.version != expected_version:
            raise ValueError(
                f"Scratchpad version conflict: expected v{expected_version}, but document is at v{doc.version}."
            )

        if op == ScratchpadPatchOp.REPLACE:
            return self._doc_manager.update_document(doc, new_content=payload, timestamp=timestamp)

        elif op == ScratchpadPatchOp.APPEND:
            sep = "\n" if doc.content and not doc.content.endswith("\n") else ""
            new_content = f"{doc.content}{sep}{payload}"
            return self._doc_manager.update_document(doc, new_content=new_content, timestamp=timestamp)

        elif op == ScratchpadPatchOp.TOGGLE_TODO:
            new_content = self._toggle_todo_line(doc.content, target_line)
            return self._doc_manager.update_document(doc, new_content=new_content, timestamp=timestamp)

        elif op == ScratchpadPatchOp.LINE_PATCH:
            if target_line is None or target_line < 1:
                raise ValueError("target_line (1-indexed) must be specified for LINE_PATCH op.")
            new_content = self._patch_line(doc.content, target_line, payload)
            return self._doc_manager.update_document(doc, new_content=new_content, timestamp=timestamp)

        raise ValueError(f"Unsupported patch operation: {op}")

    def append_todo_item(
        self,
        doc: ScratchpadDocument,
        todo_text: str,
        is_completed: bool = False,
        timestamp: float | None = None,
    ) -> ScratchpadDocument:
        """Helper appending a standard Markdown checkbox item to the scratchpad."""
        box = "[x]" if is_completed else "[ ]"
        line_item = f"- {box} {todo_text.strip()}"
        return self.apply_patch(
            doc=doc,
            op=ScratchpadPatchOp.APPEND,
            payload=line_item,
            timestamp=timestamp,
        )

    def _toggle_todo_line(self, content: str, target_line: int | None) -> str:
        lines = content.splitlines()
        if not lines:
            return content

        # If line number specified, toggle that specific line
        if target_line is not None:
            idx = target_line - 1
            if 0 <= idx < len(lines):
                lines[idx] = self._toggle_line_checkbox(lines[idx])
            return "\n".join(lines)

        # Otherwise toggle the first pending todo found
        for i, line in enumerate(lines):
            if re.search(r"[-*]\s*\[\s*\]", line):
                lines[i] = self._toggle_line_checkbox(line)
                break
        return "\n".join(lines)

    def _toggle_line_checkbox(self, line: str) -> str:
        if re.search(r"[-*]\s*\[\s*\]", line):
            return re.sub(r"([-*]\s*)\[\s*\]", r"\1[x]", line, count=1)
        elif re.search(r"[-*]\s*\[[xX]\]", line):
            return re.sub(r"([-*]\s*)\[[xX]\]", r"\1[ ]", line, count=1)
        return line

    def _patch_line(self, content: str, target_line: int, payload: str) -> str:
        lines = content.splitlines()
        idx = target_line - 1
        if 0 <= idx < len(lines):
            lines[idx] = payload
        else:
            # Extend lines if beyond current length
            while len(lines) < idx:
                lines.append("")
            lines.append(payload)
        return "\n".join(lines)
