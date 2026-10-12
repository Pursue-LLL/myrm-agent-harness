# ipc/

## Overview

Safe Subprocess and File-Descriptor IPC Pipeline module. Harness core security subsystem for shell-free, injection-proof inter-process communication.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Safe Subprocess and File-Descriptor IPC Pipeline module — Harness core security subsystem for shell-free, injection-proof inter-process communication. | ✅ |
| pipeline.py | Core | Safe Subprocess and IPC Pipeline eliminating shell injection risks — Harness core security pipeline. Replaces command line string concatenation with pure POSIX file descriptors or 0600 temporary query files, preventing shell quotation crashes and RCE. | ✅ |
| secure_file.py | Core | Secure temporary file lifecycle with POSIX 0600 permissions and zero-trace wiping — Harness core security module. Eliminates command-line string parameter vulnerabilities by storing queries in 0600-mode temporary files, and shredding all bytes upon exit. | ✅ |
| types.py | Core | Type definitions for Safe File-Descriptor and Query-File IPC Pipeline — Harness core security subsystem for shell-free, injection-proof inter-process communication. | ✅ |
