# escalation/

## Overview

L4 remote fetch extension point for `FetchEngine`. Framework defines Protocol, DTOs,
ContextVar binding, and metrics only — httpx vendor implementations live in
`myrm-agent-server/app/services/web_fetch/providers/`.

## Files

| File | Role | I/O/P |
|------|------|-------|
| protocols.py | `FetchEscalationProvider` Protocol + `EscalationFetchResult` | ✅ |
| context.py | Per-run ContextVar bind (`bind_web_fetch_escalation_context`) | ✅ |
| metrics.py | `WebFetchEscalationMetrics` counters | ✅ |
| __init__.py | Public re-exports | ✅ |

## Usage

Server binds providers per agent stream; `FetchEngine._try_escalation` reads
`get_bound_escalation_providers()` after L1-L3 failure.
