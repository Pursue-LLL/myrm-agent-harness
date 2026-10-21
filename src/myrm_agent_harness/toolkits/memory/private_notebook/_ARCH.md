# Transparent Inspectable Model Private Notebook Suite Architecture

## 1. Problem Statement & Motivation
In long-horizon agent execution (multi-hour coding, system debugging, complex research):
- **Traditional Auto-Compact Pathology**: Traditional agents irreversibly compress conversational history into lossy summaries. Critical negative feedback, rejected hypotheses, and precise error signatures get pruned. Consequently, 20 turns later, the agent loops back and re-attempts the exact same failing strategy.
- **OpenAI Codex PR #42385 Paradigm**: Codex rust-v0.153.0 eliminated lossy irreversible compaction and granted models autonomous context management:
  - 4 History tools: `list_history_contexts`, `list_history_entries`, `read_history_entry`, `search_history`.
  - 5 Notes tools: `list_notes`, `read_note`, `search_notes`, `append_note`, `rewrite_note`.
  - Context rotation: `new_context` tool cleans the context window while keeping sandbox state and disk files alive.
  - Auto-compaction downgraded to a secondary fallback.
- **Myrm Counter-Supervention (Overcoming Codex Flaws)**:
  - **Local-First & Inspectable**: Unlike Codex's blackbox cloud storage, Myrm notes are stored as readable Markdown files under the sandbox workspace: `.myrm/agent_notes/*.md`.
  - **Human-in-the-Loop Verification**: Notes can be viewed, reviewed, edited, or corrected by users in real-time via WebUI/desktop drawer, preventing agent delusion.
  - **BYOK & Triple-Parity**: Works seamlessly across Local WebUI, Tauri desktop app, and cloud-managed sandboxes with any LLM provider.

## 2. Component Design
- `models.py`: Immutable data contracts (`NoteEntry`, `NoteMetadata`, `NoteSearchResult`, `HistoryContextItem`, `HistoryEntryItem`, `NewContextResult`).
- `storage.py`: `LocalInspectableNoteStorage` handles thread-safe disk I/O, regex token search, safe file name sanitization, and atomic overwriting.
- `history_manager.py`: `HistoryContextManager` indexes multi-window past conversations and tool outputs for cross-window search.
- `tools.py`: `PrivateNotebookToolKit` packages the 10 autonomous tools (History 4 + Notes 5 + NewContext 1) with standardized schemas.
- `manager.py`: `ModelPrivateNotebookManager` ties together storage, history, active context ID, and `new_context` handover.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for private notebook. | ✅ |
| `history_manager.py` | Core | Thread-safe catalog indexing multi-window historical agent interactions and tool invocations. | ✅ |
| `manager.py` | Core | Unified orchestrator for local inspectable private notes, cross-context recall, and seamless rotation. | ✅ |
| `models.py` | Types | Types and models for private notebook. | ✅ |
| `storage.py` | Core | Thread-safe, human-inspectable filesystem storage for model private notes in Markdown. | ✅ |
| `tools.py` | Core | Encapsulates the 10 autonomous tools for model private notes, history recall, and context handover. | ✅ |
