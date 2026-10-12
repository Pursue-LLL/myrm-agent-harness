# device_whitelist/

## Overview

Sandbox Container Device Whitelist Hardening and Block Device Strip Suite. CodePilot-aligned virtual pseudo-device allowlist and physical block device strip suite. Confines container execution to safe virtual devices (/dev/null, /dev/zero, /dev/full, /dev/random, /dev/urandom, /dev/tty) and completely strips block devices (/dev/sd*, etc.).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Sandbox Container Device Whitelist Hardening and Block Device Strip Suite — CodePilot-aligned virtual pseudo-device allowlist and physical block device strip suite. Confines container execution to safe virtual devices (/dev/null, /dev/zero, /dev/full, /dev/random, /dev/urandom, /dev/tty) and completely strips block devices (/dev/sd*, etc.). | ✅ |
| facade.py | Core | Facade for Sandbox Container Device Whitelist Hardening — Main entry point for container device hardening in harness. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| sanitizer.py | Core | Device sanitizer and allowlist engine for sandbox containers — Device-level sandbox security boundary. Enforces minimal virtual pseudo-device allowlist and strips physical block devices and host hardware nodes. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
| types.py | Core | Type definitions for Sandbox Container Device Whitelist Hardening — Core schema definitions for CodePilot-aligned virtual device allowlist and block device stripping. Strictly avoids Any types; enforced under 400 lines limit. | ✅ |
