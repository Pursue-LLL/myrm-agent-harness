# Bitemporal Truth Maintenance Filter Suite Architecture

## Overview
Provides bitemporal half-open interval coordinate tracking, non-destructive evidence
retraction, and truth maintenance justification graph evaluation for agent memory.

## Architectural Responsibilities
1. **Bitemporal Half-Open Interval Calculus (`interval_algebra.py`)**:
   Enforces mathematically rigorous `[start, end)` half-open intervals for both Valid Time
   (reality timeline) and Known/Transaction Time (system awareness timeline), preventing boundary ambiguities.
2. **Data Contracts & Snapshots (`models.py`)**:
   Zero-`Any`, immutable, typed models representing evidence records, bitemporal coordinates,
   support dependencies, and truth maintenance snapshots with causal distance tracking.
3. **Truth Maintenance Graph (`support_graph.py`)**:
   Maintains premise-inference justification graphs. Implements non-destructive retraction
   (setting `retracted_at` while preserving physical records) and recursive active support verification.
4. **Bitemporal Filter & Projection Engine (`temporal_filter.py`)**:
   Enables "as-of" time-travel queries across dual dimensions, strictly filtering by active justification
   support to prevent stale, retracted, or invalidated memories from entering prompt contexts.
5. **Unified Public Facade (`facade.py`)**:
   Exposes high-level operations for recording facts, deriving inferences, retracting evidence,
   and projecting verified inference snapshots.

## File Manifest
| File | Responsibility |
| :--- | :--- |
| `models.py` | Data contracts, enums, and snapshot models |
| `interval_algebra.py` | Half-open interval operations and geometry |
| `support_graph.py` | Justification graph and recursive TMS cascade evaluation |
| `temporal_filter.py` | Multi-dimensional as-of time-travel query filter |
| `facade.py` | Public API facade and convenience factories |
| `__init__.py` | Package entrypoint and clean symbol exports |
