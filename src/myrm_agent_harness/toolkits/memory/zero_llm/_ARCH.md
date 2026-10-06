# zero_llm/

## Overview

Zero-LLM local memory capture and rule-based FTS graph retrieval engine.
Provides deterministic, zero-cost memory extraction across 6 semantic categories,
sub-millisecond lexical FTS5 and 1-hop [[Wikilink]] graph topology retrieval,
and a progressive enhancement gate with graceful fail-open degradation.

## File Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| `__init__.py` | Package | Public export barrel for Zero-LLM memory subsystem. | — |
| `types.py` | Core | Typed fact categories, extracted rule facts, search hits, and engine configurations. | ✅ |
| `rule_extractor.py` | Core | Deterministic regex and pattern-based rule extraction engine (6 high-signal categories). | ✅ |
| `fts_graph_retriever.py` | Core | SQLite FTS5 lexical matcher and 1-hop [[Wikilink]] graph topological neighbor expander. | ✅ |
| `progressive_gate.py` | Core | Progressive enhancement gate with fail-open fallback to pure deterministic path. | ✅ |
| `engine.py` | Core | Unified facade engine coordinating zero-cost capture and graph retrieval. | ✅ |
