# cardinality_cap/

## Overview
Safeguards Prometheus metrics collectors and process memory from label cardinality explosion.
Inspired by Headroom's inbound request-path cardinality cap (`perf(metrics): cap inbound request-path cardinality to bound memory (#3340)`).
Normalizes dynamic URL parameters into static placeholders (`/session/{id}`), enforces configurable ceilings per hot-path metric (e.g. 256), and safely routes overflowing new labels to an `_overflow_` sentinel bucket.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of governor and models. | ✅ |
| `models.py` | Domain Models | Pydantic data schemas for cardinality statistics, configuration, and health statuses. | ✅ |
| `governor.py` | Core Governor | MetricCardinalityGovernor enforcing normalization, cap ceilings, and overflow bucket routing. | ✅ |
