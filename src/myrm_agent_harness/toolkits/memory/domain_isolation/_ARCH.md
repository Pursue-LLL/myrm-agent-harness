# Connection and Account Domain Isolation Architecture

## Overview
The Connection and Account Domain Isolation layer addresses the critical data sovereignty gap where connectors and memory writes previously only had global toggles. It enables explicit user-declared partitioning between work (`work`) and personal (`personal`) domains, independent domain-scoped grants (recall, write, proactive care, and egress), default active-domain recall boundaries, and hard privacy redlines that prevent personal domain content from accidentally leaking to external enterprise channels.

## Components

| File | Type | Description |
|---|---|---|
| `models.py` | Data Models | Domain models including `DataDomain`, `DomainGrantConfig`, `ConnectorDomainBinding`, `DomainRecallFilter`, and `EgressDecision`. |
| `domain_registry.py` | Registry & Store | Persists connector-domain bindings and manages independent domain grant configurations with disk/memory support. |
| `domain_guard.py` | Security Guard | Enforces write permissions, cross-domain recall boundaries, and strict outbound channel egress redlines. |
| `__init__.py` | Facade | Public package API exports. |

## Data Flow
```
[External Channel / Connector Account]
                 │
                 ▼
     DomainIsolationRegistry
      (work / personal binding)
                 │
  ┌──────────────┴──────────────┐
  ▼                             ▼
DomainIsolationGuard       DomainIsolationGuard
 (Recall & Write Gate)     (Outbound Egress Redline)
  │                             │
  ├─ Work -> Work (Allowed)     ├─ Work Egress (Permitted by grant)
  ├─ Work -> Personal (Blocked) └─ Personal Egress (Blocked unless confirmed)
  └─ Explicit Cross-domain (Flagged)
```
