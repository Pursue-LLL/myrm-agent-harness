# inbound_quarantine/

## Overview

Inbound Zero-Trust Quarantine & Redaction Gate Suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Inbound Zero-Trust Quarantine & Redaction Gate Suite | ✅ |
| gate.py | Core | Composite Inbound Zero-Trust Quarantine Gate — Unified boundary orchestrating sniffer detection and ephemeral vault isolation. | ✅ |
| sniffer.py | Core | Zero-trust credential sniffer detecting OTPs, reset links, and statements — Pre-LLM inspection gate ensuring model prompts never receive raw credentials. | ✅ |
| types.py | Core | Core data structures and types for Inbound Zero-Trust Quarantine & Redaction — Harness core security contracts for inbound credential isolation. | ✅ |
| vault.py | Core | Encrypted ephemeral quarantine vault for intercepted credentials — Physical isolation barrier ensuring raw secrets never enter persistent agent memory. | ✅ |
