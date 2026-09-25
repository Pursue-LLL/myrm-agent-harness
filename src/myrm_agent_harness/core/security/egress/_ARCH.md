# core/security/egress/

## Overview
Ephemeral sentinel voucher encoding/decoding and loopback egress proxy substitution for agent execution environments. Eliminates raw API keys and secrets from child process environments (mitigating prompt-injection secret extraction and rogue dependency scraping) by replacing credentials with ephemeral AES-256-GCM sentinel tokens and transparently restoring raw values at the loopback proxy egress boundary.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public aggregation facade exposing `SentinelManager`, `StreamingSentinelScanner`, `EphemeralCaManager`, `LoopbackEgressProxy`, `SpendGovernor`, and `TaintedEgressGateway`. | — |
| `sentinel.py` | Core | Ephemeral AES-256-GCM voucher tokenization (`myrm-sent-v1.<base64url>.end`), fast in-memory reverse lookup, text/bytes replacement, and sliding-window stream scanner. | ✅ |
| `proxy_server.py` | Core | Asyncio-based loopback egress proxy (`LoopbackEgressProxy`) with ephemeral CA management (`EphemeralCaManager`) for outbound HTTP/CONNECT request header, query, and streaming body substitution. | ✅ |
| `spend_contracts.py` | Core | Immutable data models and token primitives (`SpendGovernorConfig`, `SpendLease`, `SpendLeaseResult`, `SpendCommitResult`, `is_spend_voucher`) for zero-float commerce accounting. | ✅ |
| `spend_governor.py` | Core | Pure deterministic micro-spending state machine (`SpendGovernor`) enforcing merchant allowlists, per-action/daily caps in USD Cents, atomic leases, and voucher generation. | ✅ |
| `tainted_gateway.py` | Core | Transport-level network egress gateway (`TaintedEgressGateway`, `TaintedEgressDecision`, `TaintedEgressBlockedError`) enforcing taint-based leak prevention, domain allowlists, and ContextVar tracking. | ✅ |

## Key Invariants

1. **Zero Raw Secret in Child Env**: Child process environments only receive unforgeable sentinel vouchers.
2. **Ephemeral Lifecycle**: In-memory keys are strictly process-bound and never written to disk.
3. **No Prompt Cache Impact**: Secret substitution and spend governance evaluate strictly in the interceptor and network proxy layer outside LLM prompts.
4. **Zero-Float Accounting**: All commerce spending operations enforce integer USD Cents calculations to eliminate floating point rounding errors.
5. **Taint-Aware Egress Gating**: Once a session accesses sensitive files or secrets, outbound connections are blocked at the transport layer unless pre-authorized via static allowlists or human approval.
