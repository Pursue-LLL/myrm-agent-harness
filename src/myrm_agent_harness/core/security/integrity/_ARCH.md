# core/security/integrity/

## Overview
Domain for cryptographic integrity checking, corruption detection, and atomic persistence sealing.
Ensures persisted snapshots and incremental checkpoints are strictly validated against torn writes,
bitflips, and unsealed incomplete transfers before being loaded into execution sandboxes.

## Files

| File | Description |
|---|---|
| `seal.py` | `SealManifest`, `IntegritySealer`, `FileChecksum`, `IntegrityStatus`, `IntegrityVerificationResult` |
| `__init__.py` | Module facade exporting all integrity and sealing types |
