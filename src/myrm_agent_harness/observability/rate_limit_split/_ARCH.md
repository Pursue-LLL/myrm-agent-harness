# rate_limit_split/

## Overview
Rate Limit Source Split Suite.
Splits 429 rate limit events into local governor rejections (`myrm`) versus upstream provider refusals (`upstream`), while attributing failure causes to specific model providers (Anthropic, OpenAI, DeepSeek, etc.).

Crucially, the unlabelled total counters (`total_rate_limited` and `total_failed`) remain invariant and monotonic to prevent metric drift and backward incompatibility with existing monitoring scrapers.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public exports for RateLimitSource, RateLimitSplitTracker, and snapshots. | ✅ |
| `models.py` | DTO & Enums | Immutable data structures for split rate limits, failure attribution, and snapshots. | ✅ |
| `tracker.py` | Core Collector | Thread-safe in-memory metrics tracker maintaining pre-seeded zero buckets. | ✅ |

## Design Constraints & Principles
1. **Unlabelled Totals Invariant**: `total_rate_limited` and `total_failed` must accurately reflect total unpartitioned counts.
2. **Pre-seeded Buckets**: Initial maps seed `"myrm": 0, "upstream": 0` and `"unknown": 0` to prevent Prometheus vector drop / empty alerts on healthy systems.
3. **Thread Safety**: Concurrent request calls in high-throughput pipelines must increment atomic counters under lock protection.
4. **Zero Any Typing**: Strict typed models without Any.
