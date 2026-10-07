# Universal Context Ingestion Gateway Architecture

## Overview
This package implements the Universal Context Ingestion Gateway and Hardware Voice Sync Suite (Item 75). It ingests heterogeneous multi-modal transcript sources (Plaud voice recording card JSON, WebVTT, SRT, raw transcripts), extracts speakers, actions, and decisions, and enforces SQLite-backed idempotency deduplication.

## Core Modules
- `models.py`: Strongly typed primitives (`IngestionSourceType`, `VoiceTranscriptSegment`, `ContextIngestionPayload`, `IngestionDigestResult`).
- `parser.py`: `TranscriptUniversalParser` decoding multi-source formats into normalized segment sequences.
- `dedup.py`: `IngestionIdempotencyGuard` providing SHA-256 fingerprint hashing and SQLite deduplication registry.
- `distiller.py`: `VoiceContextDistiller` merging adjacent speaker utterances and extracting decisions/action items.
- `gateway.py`: `UniversalContextIngestionGateway` facade orchestrating end-to-end ingestion and distillation.
- `__init__.py`: Public package exports conforming to harness conventions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for ingestion gateway. | ✅ |
| `dedup.py` | Core | SQLite-backed idempotency guard preventing duplicate context ingestion. | ✅ |
| `distiller.py` | Core | Distiller that merges adjacent speaker utterances and extracts decisions/actions. | ✅ |
| `gateway.py` | Core | Universal ingestion gateway for hardware voice cards and multi-source contexts. | ✅ |
| `models.py` | Types | Types and models for ingestion gateway. | ✅ |
| `parser.py` | Core | Universal parser for multi-modal audio transcripts and hardware recorder payloads. | ✅ |
