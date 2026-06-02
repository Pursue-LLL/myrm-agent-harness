# health/

## Overview
Health checking infrastructure layer. Provides abstract interfaces and coordinator for resource health checks and automatic recovery, independent of specific storage technologies.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Health checking infrastructure exports. | ✅ |
| health_checker.py | Core | HealthChecker abstract base class, HealthCheckResult and RecoveryResult models. | ✅ |
| coordinator.py | Core | Health check coordinator that runs all checkers sequentially and attempts recovery. | ✅ |

## Module Dependencies

**Internal Dependencies:**
- None (framework-level, no dependencies on business logic)

**Used By:**
- `app/core/infra/health/` — Business-level health checker implementations
- `app/run.py` — Startup health check integration
