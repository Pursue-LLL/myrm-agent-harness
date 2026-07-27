# bm25/

## Overview
BM25 retrieval module providing CJK/English hybrid tokenization for sparse retrieval.

## Architecture Decisions

- **CJK Fallback Strategy**: When `jieba` is unavailable, uses character unigram + bigram tokenization (industry standard, same as openclaw/CodePilot). This ensures partial-match recall for Chinese text.
- **Backend Property**: `TokenizerService.backend` exposes the active backend ("jieba" or "bigram_fallback") for diagnostics and health checks.
- **English Normalization**: Zero-dependency stopword + conservative suffix rules (-ies/-ing/-ed only) in `english_normalizer.py`. Opt in via `enable_english_enhancement` on `BM25Retriever`; `SkillSearchEngine` keeps it off by default.
- **Diagnostic Integration**: Registered via `check_tokenizer_health` probe in `diagnostics/probes.py`.

## File & Submodule Index

| File | Role | Description |
|------|------|-------------|
| __init__.py | Package | Exports TokenizerService, get_tokenizer_service, preload_tokenizer, _cjk_bigram_tokenize |
| tokenizer.py | Core | Unified tokenization service with jieba + CJK bigram fallback + native English normalization |
| english_normalizer.py | Core | Zero-dependency English stopword + suffix normalization for BM25 |
