# desktop_oauth_device/

## Overview

Desktop OAuth Browser Flow & RFC 8628 Device Code Grant Engine Suite. Harness core security package for zero-plaintext API key identity management.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Desktop OAuth Browser Flow & RFC 8628 Device Code Grant Engine Suite — Harness core security package for zero-plaintext API key identity management. | ✅ |
| device_code_engine.py | Core | RFC 8628 Device Authorization Grant Engine for headless and sandbox environments — Harness core security engine enabling zero-API-key logins via external browser/mobile. | ✅ |
| pkce.py | Core | RFC 7636 PKCE (Proof Key for Code Exchange) generation and verification engine — Harness core security engine securing desktop OAuth flows against interception. | ✅ |
| token_rotator.py | Core | Silent Token Auto-Rotation and Lifecycle Management Engine — Harness core security engine guaranteeing uninterrupted agent sessions via background token renewal. | ✅ |
| types.py | Core | Domain models and types for Desktop OAuth Browser Flow & RFC 8628 Device Code Grant — Harness core security domain models for zero plaintext API key transmission. | ✅ |
