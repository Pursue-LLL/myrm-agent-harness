# provider_window/

## Overview
One typed fact — the absolute time a rate-limited provider will serve again — extracted once from an LLM exception and consumed by stream recovery, credential cooldown and error diagnostics. Consumers never re-parse headers or bodies.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Facade: re-exports the hint types, the two extractor functions and `deferral_wait_s`. | ✅ |
| deferral.py | Core | `deferral_wait_s()`: seconds a goal-less host (cron job, kanban task) may defer after a failed run, read from `MyrmLLMError.context['cooldown_remaining_ms']`; None when no boundary or beyond the 24 h hold cap. | ✅ |
| extract.py | Core | `extract_provider_window()` / `has_rejected_quota_window()`: merges headers across the `__cause__`/`__context__` chain, then reads Anthropic unified rejected windows (duration-named `5h`/`7d` buckets only — the `overage` pay-as-you-go pool is no window and reads `rejected` on accounts without credits even while every window is open; max reset; any rejected window without a usable reset yields no hint) > Codex/OpenAI body `resets_at` / `resets_in_seconds` > `Retry-After` (seconds or HTTP-date) > "retry after N seconds" message text. Rejects past, non-finite and >366-day values. | ✅ |
| types.py | Types | `ProviderWindowHint` (reset_at, wait_s, source, quota_window), `WindowKind` (in_turn ≤300 s / hold ≤24 h / beyond), `WindowSource`, the two class boundaries. | ✅ |
