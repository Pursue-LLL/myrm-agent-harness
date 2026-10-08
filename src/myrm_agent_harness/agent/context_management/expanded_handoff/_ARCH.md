# expanded_handoff

Architecture and module inventory for the `expanded_handoff` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting expanded dialogue handoff models, builder, archive conduit, and facade suite |
| `expanded_handoff_suite.py` | Comprehensive facade suite for 1,200-word expanded dialogue skeleton and searchable archive handoff |
| `expanded_skeleton_anchor_builder.py` | Expanded 1,200-word dialogue skeleton anchor builder for high-fidelity cross-session handoffs |
| `handoff_types.py` | Domain models and contracts for 1,200-word expanded skeleton anchor and searchable archive handoffs |
| `searchable_old_session_archive_conduit.py` | Searchable archive conduit delivering on-demand recall across immutable origin session transcripts |
