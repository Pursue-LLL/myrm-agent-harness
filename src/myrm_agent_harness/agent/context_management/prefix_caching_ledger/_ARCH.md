# prefix_caching_ledger

Architecture and module inventory for the `prefix_caching_ledger` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting prefix caching models, layout engine, auditor, and ledger suite |
| `prefix_caching_types.py` | Domain models and contracts for prefix caching aligned layout and hidden reasoning token ledger |
| `prefix_caching_aligned_layout_engine.py` | Deterministic three-tier layout assembler enforcing byte-level prefix stability and KV-cache reuse |
| `hidden_reasoning_tokens_penetration_auditor.py` | Auditor extracting hidden reasoning tokens and prefix cache usage across heterogeneous providers |
| `multi_dimensional_session_token_ledger.py` | Session-scoped immutable audit ledger tracking all token dimensions across conversation turns |
| `prefix_caching_aligned_context_layout_and_hidden_reasoning_token_ledger_suite.py` | Unified facade suite orchestrating prefix-caching aligned context layout and hidden reasoning token ledgers |
