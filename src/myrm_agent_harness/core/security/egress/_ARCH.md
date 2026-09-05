# core/security/egress/

## Overview
Ephemeral sentinel voucher encoding/decoding and loopback egress proxy substitution for agent execution environments. Eliminates raw API keys and secrets from child process environments (mitigating prompt-injection secret extraction and rogue dependency scraping) by replacing credentials with ephemeral AES-256-GCM sentinel tokens and transparently restoring raw values at the loopback proxy egress boundary.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public aggregation facade exposing `SentinelManager`, `StreamingSentinelScanner`, `EphemeralCaManager`, and `LoopbackEgressProxy`. | — |
| `sentinel.py` | Core | Ephemeral AES-256-GCM voucher tokenization (`myrm-sent-v1.<base64url>.end`), fast in-memory reverse lookup, text/bytes replacement, and sliding-window stream scanner. | ✅ |
| `proxy_server.py` | Core | Asyncio-based loopback egress proxy (`LoopbackEgressProxy`) with ephemeral CA management (`EphemeralCaManager`) for outbound HTTP/CONNECT request header, query, and streaming body substitution. | ✅ |

## Key Invariants

1. **Zero Raw Secret in Child Env**: Child process environments only receive unforgeable sentinel vouchers.
2. **Ephemeral Lifecycle**: In-memory keys are strictly process-bound and never written to disk.
3. **No Prompt Cache Impact**: Secret substitution occurs strictly in the network proxy layer below the LLM prompt layer.
