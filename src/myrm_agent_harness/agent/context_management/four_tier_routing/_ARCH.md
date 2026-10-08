# four_tier_routing

Architecture and module inventory for the `four_tier_routing` package.

## Modules

| File | Description |
| --- | --- |
| `__init__.py` | Package entry point exporting four-tier context types, router, JIT protocol, synthesis engine, and facade suite |
| `four_tier_types.py` | Domain contracts, tier kinds, domain kinds, triggered rules, JIT handles, and synthesized directives |
| `triggered_context_router.py` | Dynamic router matching specialized domain rules (DB, API, Security, UI) based on target paths and query intent |
| `jit_retrieval_protocol.py` | Protocol managing lightweight reference handles and on-demand content hydration to minimize prompt size |
| `knowledge_synthesis_engine.py` | Pre-prompt synthesis engine distilling heterogeneous ADRs, documentation, and bug reports into actionable directives |
| `four_tier_context_suite.py` | Unified facade suite orchestrating deterministic baseline, triggered rules, JIT catalog, and knowledge synthesis |
