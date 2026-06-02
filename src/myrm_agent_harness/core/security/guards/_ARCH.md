# core/security/guards/

## Overview
Session-level security guards — privacy tracking and SSRF prevention.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Module docstring. | — |
| privacy_tracker.py | Core | Privacy tracker — per-turn PII sensitivity tracking, ContextVar-based privacy policy access (set/get_privacy_policy). | ✅ |
| ssrf_guard.py | Core | SSRF guard — validates URLs against allowlists to prevent server-side request forgery. | ✅ |

## Key Dependencies

- No internal dependencies (foundation layer)
