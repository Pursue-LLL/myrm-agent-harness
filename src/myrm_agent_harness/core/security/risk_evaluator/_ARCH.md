# risk_evaluator/

## Overview

Independent Risk Evaluator Agent and OS-Level Security Scanner module. Harness core security subsystem providing multi-agent independent risk checks and OS-level security scanning.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Independent Risk Evaluator Agent and OS-Level Security Scanner module — Harness core security subsystem providing multi-agent independent risk checks and OS-level security scanning. | ✅ |
| audit_ledger.py | Core | Structured Risk Audit Ledger for persistent compliance tracking — Harness core security subsystem. Maintains audit trail of risk assessments, enabling non-repudiable post-mortem analysis and regulatory compliance. | ✅ |
| evaluator_agent.py | Core | Independent Risk Evaluator Agent implementing risk-first dual-validation — Harness core multi-agent safety layer inspired by AutoHedge (segregated risk evaluation agent). Ensures high-impact proposals are judged independently before execution. | ✅ |
| os_security_guard.py | Core | Cross-host OS-level runtime security scanner and safe operator matrix — Harness core security module inspired by ECC (Hermes safe operator matrix). Blocks destructive terminal commands, unauthenticated network egress, and credential sniffing. | ✅ |
| types.py | Core | Type definitions for Independent Risk Evaluator Agent and OS Security Scanner — Harness core security subsystem providing multi-agent independent risk checks (AutoHedge inspired) and OS-level safe operator scanning (ECC inspired). | ✅ |
