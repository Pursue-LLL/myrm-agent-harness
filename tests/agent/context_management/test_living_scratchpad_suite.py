# [INPUT]: LivingScratchpadConfig, LivingScratchpadDocumentManager, LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite, ScratchpadBidirectionalPatcher, ScratchpadConduitInjection, ScratchpadContextConduit, ScratchpadDocument, ScratchpadPatchOp, ScratchpadScope, ScratchpadTodoItem
# [OUTPUT]: test_living_scratchpad_suite.py
# [POS]: tests/agent/context_management/test_living_scratchpad_suite.py

"""Comprehensive unit tests for LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite.

Verifies:
1. Document creation, isolation (session vs global), and Markdown checklist parsing (- [ ] / - [x]).
2. Atomic patch mutations (REPLACE, APPEND, TOGGLE_TODO, LINE_PATCH) with version monotonic increments.
3. Optimistic concurrency conflict rejection when expected_version mismatches.
4. XML context conduit injection formatting and token consumption estimation.
5. Actionable pending checklist extraction into formatted agent execution prompt.
6. System prompt augmentation and clean session cleanup.
7. End-to-end facade orchestration.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.living_scratchpad import (
    LivingScratchpadConfig,
    LivingScratchpadDocumentManager,
    LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite,
    ScratchpadBidirectionalPatcher,
    ScratchpadConduitInjection,
    ScratchpadContextConduit,
    ScratchpadDocument,
    ScratchpadPatchOp,
    ScratchpadScope,
    ScratchpadTodoItem,
)


def test_document_lifecycle_and_todo_parsing() -> None:
    """Verifies document creation, scope isolation, and accurate Markdown checkbox parsing."""
    mgr = LivingScratchpadDocumentManager(LivingScratchpadConfig(max_content_chars=4096))
    t0 = 1000.0

    initial_md = (
        "# Project Tasks\n"
        "- [ ] Set up database schema\n"
        "- [x] Initialize Git repository\n"
        "- [ ] Configure CI pipeline\n"
    )

    doc = mgr.get_or_create_session_pad("session-101", title="Deployment Pad", initial_content=initial_md, timestamp=t0)
    assert doc.scope == ScratchpadScope.SESSION_SCOPED
    assert doc.session_id == "session-101"
    assert doc.title == "Deployment Pad"
    assert doc.version == 1
    assert len(doc.todos) == 3

    # Check parsed todos details
    assert doc.todos[0].text == "Set up database schema"
    assert doc.todos[0].is_completed is False
    assert doc.todos[0].line_number == 2

    assert doc.todos[1].text == "Initialize Git repository"
    assert doc.todos[1].is_completed is True
    assert doc.todos[1].line_number == 3

    assert doc.completed_todos_count == 1
    assert doc.pending_todos_count == 2
    assert doc.has_pending_todos is True

    # Global document isolation
    glob_doc = mgr.get_or_create_global_pad("workspace_global", title="Global Memo")
    assert glob_doc.scope == ScratchpadScope.GLOBAL_SCOPED
    assert glob_doc.session_id is None
    assert mgr.total_documents_count == 2


def test_bidirectional_co_editing_patch_operations() -> None:
    """Verifies atomic patch mutations: REPLACE, APPEND, TOGGLE_TODO, LINE_PATCH."""
    mgr = LivingScratchpadDocumentManager()
    patcher = ScratchpadBidirectionalPatcher(mgr)
    t0 = 2000.0

    doc = mgr.get_or_create_session_pad("session-edit", initial_content="- [ ] Item 1\n- [ ] Item 2\n", timestamp=t0)
    assert doc.version == 1

    # 1. APPEND patch
    doc = patcher.apply_patch(doc, ScratchpadPatchOp.APPEND, payload="- [ ] Item 3", timestamp=t0 + 1.0)
    assert doc.version == 2
    assert len(doc.todos) == 3
    assert "Item 3" in doc.content

    # 2. TOGGLE_TODO (line 1)
    doc = patcher.apply_patch(doc, ScratchpadPatchOp.TOGGLE_TODO, payload="", target_line=1, timestamp=t0 + 2.0)
    assert doc.version == 3
    assert doc.completed_todos_count == 1
    assert doc.todos[0].is_completed is True

    # 3. LINE_PATCH (replace line 2)
    doc = patcher.apply_patch(doc, ScratchpadPatchOp.LINE_PATCH, payload="- [x] Item 2 Modified", target_line=2, timestamp=t0 + 3.0)
    assert doc.version == 4
    assert "Item 2 Modified" in doc.content
    assert doc.completed_todos_count == 2

    # 4. REPLACE patch (overwrite all)
    doc = patcher.apply_patch(doc, ScratchpadPatchOp.REPLACE, payload="Clean Notes without todos", timestamp=t0 + 4.0)
    assert doc.version == 5
    assert doc.content == "Clean Notes without todos"
    assert len(doc.todos) == 0

    # 5. Optimistic concurrency check (version mismatch)
    with pytest.raises(ValueError, match="version conflict"):
        patcher.apply_patch(doc, ScratchpadPatchOp.APPEND, payload="Test", expected_version=3)


def test_context_conduit_xml_injection_and_tokens() -> None:
    """Verifies XML formatted context conduit injection with todo metadata and token estimation."""
    mgr = LivingScratchpadDocumentManager()
    conduit = ScratchpadContextConduit(LivingScratchpadConfig(token_char_ratio=4.0))

    # Blank document produces empty injection
    blank_doc = mgr.get_or_create_session_pad("sess-blank", initial_content="   ")
    blank_inj = conduit.serialize_injection(blank_doc)
    assert blank_inj.tag_text == ""
    assert blank_inj.estimated_tokens == 0

    # Populated document produces dense XML tag
    content = "- [x] Setup environment\n- [ ] Run benchmark tests"
    doc = mgr.get_or_create_session_pad("sess-active", initial_content=content)
    inj = conduit.serialize_injection(doc)

    assert inj.version == 1
    assert "<living_scratchpad scope=\"session_scoped\" version=\"1\" todos=\"1/2 completed\">" in inj.tag_text
    assert "Run benchmark tests" in inj.tag_text
    assert "</living_scratchpad>" in inj.tag_text
    assert inj.has_pending_todos is True
    assert inj.total_todos == 2
    assert inj.completed_todos == 1
    assert inj.estimated_tokens > 0


def test_extract_pending_todos_as_actionable_prompt() -> None:
    """Verifies extracting only unchecked checkboxes into a prompt instruction."""
    mgr = LivingScratchpadDocumentManager()
    conduit = ScratchpadContextConduit()

    content = (
        "- [x] Done item 1\n"
        "- [ ] Write unit tests for router\n"
        "- [ ] Verify memory bounds\n"
        "- [x] Done item 2\n"
    )
    doc = mgr.get_or_create_session_pad("sess-todos", title="Sprint Plan", initial_content=content)

    prompt = conduit.extract_pending_todos_prompt(doc)
    assert "Sprint Plan" in prompt
    assert "1. Write unit tests for router" in prompt
    assert "2. Verify memory bounds" in prompt
    assert "Done item 1" not in prompt


def test_system_prompt_injection() -> None:
    """Verifies appending scratchpad XML block cleanly into system prompt."""
    mgr = LivingScratchpadDocumentManager()
    conduit = ScratchpadContextConduit()

    doc = mgr.get_or_create_session_pad("sess-sys", initial_content="Temporary API keys or notes")
    base_prompt = "You are a helpful software engineer assistant."
    augmented = conduit.inject_into_system_prompt(base_prompt, doc)

    assert base_prompt in augmented
    assert "<living_scratchpad" in augmented
    assert "Temporary API keys or notes" in augmented


def test_facade_end_to_end_orchestration_and_cleanup() -> None:
    """Verifies high-level facade coordinating co-editing, todo toggling, and context injection."""
    suite = LivingScratchpadWorkingMemoryAndBiDirectionalContextConduitSuite(
        LivingScratchpadConfig(max_content_chars=8192)
    )
    session_id = "sess-facade-999"
    t0 = 3000.0

    # 1. Create pad with initial notes
    doc = suite.get_or_create_session_pad(
        session_id=session_id,
        title="Architecture Discussion",
        initial_content="# Scratchpad\n",
        timestamp=t0,
    )
    assert suite.total_documents_count == 1

    # 2. Append todos via facade helper
    doc = suite.append_todo_item(doc, "Design database migration", is_completed=False, timestamp=t0 + 1.0)
    doc = suite.append_todo_item(doc, "Review security policies", is_completed=False, timestamp=t0 + 2.0)
    assert doc.version == 3
    assert doc.pending_todos_count == 2

    # 3. Toggle first todo
    doc = suite.toggle_todo(doc, target_line=2, timestamp=t0 + 3.0)
    assert doc.version == 4
    assert doc.completed_todos_count == 1
    assert doc.pending_todos_count == 1

    # 4. Context injection inspection
    inj = suite.serialize_injection(doc)
    assert inj.version == 4
    assert "todos=\"1/2 completed\"" in inj.tag_text

    # 5. Extract actionable checklist prompt
    prompt = suite.extract_pending_todos_prompt(doc)
    assert "Review security policies" in prompt
    assert "Design database migration" not in prompt

    # 6. Cleanup
    assert suite.delete_session_pad(session_id) is True
    assert suite.total_documents_count == 0
