# living_scratchpad

Architecture and module inventory for the `living_scratchpad` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting living scratchpad types, document manager, patcher, conduit, and facade suite |
| `scratchpad_types.py` | Domain models and contracts for living scratchpad working memory and bidirectional context conduit |
| `living_scratchpad_document_manager.py` | Living scratchpad document manager storing and parsing markdown session and global pads |
| `scratchpad_bidirectional_patcher.py` | Bidirectional scratchpad patcher executing atomic patch mutations for human and agent co-editing |
| `scratchpad_context_conduit.py` | Scratchpad context conduit serializing living working memory into structured prompt tags |
| `living_scratchpad_suite.py` | Unified facade suite for living scratchpad working memory and bidirectional context conduit |
