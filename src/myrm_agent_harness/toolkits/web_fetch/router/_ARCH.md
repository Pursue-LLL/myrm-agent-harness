# router/

## Overview
unified adaptive router

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | unified adaptive router | — |
| adaptive_router.py | Core | Unified adaptive router. | ✅ |
| cost_learner.py | Core | Multi-dimensional cost learning module. | ✅ |
| domain_metrics.py | Core | Domain-level learning metrics manager. | ✅ |
| maintenance.py | Core | Provides MaintenanceManager. | ✅ |
| models.py | Core | Router data models and concurrency primitives. | ✅ |
| persistence.py | Core | Persistence management module | ✅ |
| site_experience.py | Core | Site experience store with domain-level `prefer_http3` for L1 QUIC shortcut | ✅ |

## Key Dependencies

- `infra`
