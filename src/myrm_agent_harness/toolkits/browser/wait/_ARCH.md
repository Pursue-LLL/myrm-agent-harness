# browser/wait/

## Overview

Page wait strategies — hybrid detection for optimal page ready detection. Four strategies (smart/hybrid/dom_stable/networkidle) with runtime statistics, domain-level learning, and full metrics.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade: `wait_for_page_ready`, `WaitStrategy`, `WaitMetrics`, `WaitStrategyStats`, global stats accessors | ✅ |
| `_impl.py` | Core | 4 strategy implementations (networkidle/dom_stable/smart/hybrid) + SPA stable | ✅ |
| `_types.py` | Config | Type definitions: `WaitStrategy`/`WaitMetrics`/`WaitStrategyStats` + thread-safe runtime stats | ✅ |
| `_dom_stable_js.py` | Resource | DOM stability detection JavaScript generator (MutationObserver incl. Shadow DOM) | ✅ |

## Key Dependencies

- `toolkits/web_fetch/router/domain_metrics` (domain-level metric recording, optional)
- `patchright.async_api::Page`
