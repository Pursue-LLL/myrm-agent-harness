# Verifiable Provenance & Physical Isolation Architecture

## Overview
This package implements cryptographic physical storage residency proof, strict fail-closed boundary enforcement, true physical multi-pass overwriting (right-to-be-forgotten), and pre-ingest PII interception for single-instance sandbox memory stores.

## Components
| File | Role |
| --- | --- |
| `models.py` | Immutable data models for residency proof, fail-closed context, destruction receipt, and PII shield |
| `fail_closed_guard.py` | Strict boundary gatekeeper rejecting requests with invalid or missing tenant tokens without fallback |
| `physical_residency_prover.py` | Generates transparent verifiable evidence proving dedicated unshared persistence on volume |
| `physical_purge_engine.py` | Executes multi-pass physical sector overwrites and issues immutable destruction receipts |
| `pre_ingest_pii_shield.py` | Active pre-ingest interception protecting children identity, residential addresses, and financials |
| `manager.py` | Unified coordinator facade for all verifiable provenance subsystems |
| `__init__.py` | Public API surface exports |
