# git_leak_shield/

## Overview

Zero-Trust Credential Isolation and Git Leakage Shield module. Harness core security subsystem preventing secret leaks in Git operations, enforcing in-memory secret lifecycle, and redacting outbound logs.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Zero-Trust Credential Isolation and Git Leakage Shield module — Harness core security subsystem preventing secret leaks in Git operations, enforcing in-memory secret lifecycle, and redacting outbound logs. | ✅ |
| patterns.py | Core | High-fidelity credential and secret signature patterns for Git leak detection — Harness security pattern registry. Detects 40+ credential types across AI providers, cloud vendors, VCS platforms, and private cryptographic keys. | ✅ |
| probe.py | Core | Pre-commit and pre-push secret leak detection probe — Harness core security probe. Intercepts `git commit` and `git push` commands, scanning staged diffs to prevent accidental credential leakage to public repositories. | ✅ |
| redactor.py | Core | Outbound text and log redaction filter to neutralize credential exposure — Harness core security redactor. Prevents secrets from leaking into UI displays, logs, or persistent transcripts by replacing them with masked diagnostics. | ✅ |
| types.py | Core | Type definitions for Zero-Trust Credential Isolation and Git Leakage Shield — Harness core security contracts for secret leak prevention during Git operations, ephemeral secret injection, and outbound text redaction. | ✅ |
| vault.py | Core | Ephemeral In-Memory Secret Vault for zero-disk credential isolation — Harness core security vault. Enforces the first cardinal rule of secret governance: credentials must live exclusively in memory and be injected directly into subprocess environments, never written to disk .env files. | ✅ |
