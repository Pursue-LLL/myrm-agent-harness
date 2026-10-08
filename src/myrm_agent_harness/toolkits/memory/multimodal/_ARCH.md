# multimodal/ Architecture

## Overview
Multimodal asset memory suite. Stores vision assets and sandbox artifacts (diagrams, charts, HTML reports, data sheets, source files) as long-term memory items and serves natural-language cross-modal search over them; every hit carries a UI card preview.
`MultimodalMemoryOrchestrator` is the facade that composes the feature extractor, the in-memory store and the cross-modal retriever.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade re-exporting the contracts, components and orchestrator. | ✅ |
| `models.py` | Types | Frozen data contracts: `AssetModality`, `ArtifactKind`, `MultimodalMemoryItem`, `MultimodalIngestRequest`, `MultimodalSearchQuery`, `MultimodalSearchHit`. | ✅ |
| `extractor.py` | Core | `MultimodalFeatureExtractor`: builds items from ingest requests (modality, artifact kind and MIME type taken from the file extension when left at defaults, derived tags) and projects items into UI card previews. | ✅ |
| `store.py` | Core | `MultimodalMemoryStore`: in-memory repository keyed by item id, listing by session and modality. | ✅ |
| `retriever.py` | Core | `CrossModalRetriever`: lexical relevance scoring (exact phrase in title, then summary or description, then weighted token overlap including tags) with modality, artifact-kind and session filters. | ✅ |
| `orchestrator.py` | Facade | `MultimodalMemoryOrchestrator`: ingest, search, get, card lookup and clear behind one entry point. | ✅ |

## Key Dependencies

- Standard library only; no dependency on `agent/` or other memory sub-packages.
- Inside the package: `models` <- `extractor` / `store` <- `retriever` <- `orchestrator`; `__init__` re-exports.
