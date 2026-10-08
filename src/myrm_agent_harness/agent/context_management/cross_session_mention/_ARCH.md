# cross_session_mention

Architecture and module inventory for the `cross_session_mention` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting cross-session mention types, parser, extractor, and facade suite |
| `cross_session_types.py` | Domain models and contracts for cross-session @ mention references and snapshot injection |
| `session_mention_parser.py` | Parser and identifier resolver for @Session mentions within user prompt text |
| `session_snapshot_extractor.py` | Extractor of immutable read-only snapshots from historical session records |
| `cross_session_mention_suite.py` | End-to-end facade orchestrating cross-session @ mention references and read-only snapshot injection |
