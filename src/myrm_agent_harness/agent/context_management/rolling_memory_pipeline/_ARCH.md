# rolling_memory_pipeline

Architecture and module inventory for the `rolling_memory_pipeline` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting rolling memory types, chunk streamer, state machine, and facade suite |
| `rolling_memory_types.py` | Domain models and contracts for chunk-bounded rolling memory and long-context comprehension |
| `token_bounded_chunk_streamer.py` | Streamer slicing massive documents into token-bounded chunks with paragraph boundary preservation |
| `rolling_memory_state_machine.py` | State machine managing rolling working memory progression across sequential document chunks |
| `chunk_bounded_rolling_memory_pipeline_suite.py` | End-to-end facade orchestrating token-bounded document streaming, rolling memory evolution, and artifact generation |
