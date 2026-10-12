# credential_shield/

## Overview

Public API for Credential Stdin Pipelining & Process Leakage Shield Suite. Harness core security module package entrypoint.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public API for Credential Stdin Pipelining & Process Leakage Shield Suite — Harness core security module package entrypoint. | ✅ |
| inspector.py | Core | Command line credential inspector and process table leakage analyzer — Harness core security inspector detecting secrets passed via process CLI arguments. | ✅ |
| pipeliner.py | Core | Credential Stdin Pipelining Engine and process table isolation executor — Harness core security pipeline eliminating credential exposure in Linux/container process tables. | ✅ |
| types.py | Core | Domain types and models for Credential Stdin Pipelining & Process Leakage Shield — Harness core security models preventing token sniffing via `ps aux`, `/proc/$PID/cmdline`, and OS process tables by enforcing stdin pipelining and memory zeroization. | ✅ |
| zeroizer.py | Core | Ephemeral credential zeroizer and secure memory wiper — Harness core security memory safety helper. | ✅ |
