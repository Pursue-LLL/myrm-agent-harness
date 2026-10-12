# webhook_guard/

## Overview

Package exports for Webhook Guard and Toolset Demotion. Harness core security module for untrusted webhook defense, toolset demotion, and human-in-the-loop admin approval cards.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Package exports for Webhook Guard and Toolset Demotion — Harness core security module for untrusted webhook defense, toolset demotion, and human-in-the-loop admin approval cards. | ✅ |
| demoter.py | Core | Webhook Toolset Demoter and Admin Escalation Gatekeeper — Harness core security module inspired by Hermes Agent message gateway. Enforces runtime tool demotion and human-in-the-loop escalation for external untrusted webhooks. | ✅ |
| types.py | Core | Type definitions for Untrusted Webhook Prompt Injection Defense and Toolset Demotion — Harness core security module inspired by Hermes Agent message gateway. Enforces HMAC sender trust decoupling: treats third-party webhook payloads as tainted, strips destructive tools, and gates dangerous executions behind admin approval cards. | ✅ |
