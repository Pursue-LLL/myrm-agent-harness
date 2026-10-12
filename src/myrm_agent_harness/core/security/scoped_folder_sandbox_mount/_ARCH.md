# scoped_folder_sandbox_mount/

## Overview

Scoped Folder Permission Dialog and Sandbox Dynamic Mount Suite. src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/__init__.py [INPUT] myrm_agent_harness.core.security.scoped_folder_sandbox_mount.* [OUTPUT] __all__.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Scoped Folder Permission Dialog and Sandbox Dynamic Mount Suite — src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/__init__.py [INPUT] myrm_agent_harness.core.security.scoped_folder_sandbox_mount.* [OUTPUT] __all__ | ✅ |
| dynamic_mount_manager.py | Core | Dynamic Sandbox Mount Manager for security-scoped folder projection — src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/dynamic_mount_manager.py [INPUT] time, uuid, re, pathlib, myrm_agent_harness.core.security.scoped_folder_sandbox_mount.types, myrm_agent_harness.core.security.scoped_folder_sandbox_mount.sensitive_blacklist [OUTPUT] DynamicSandboxMountManager | ✅ |
| sensitive_blacklist.py | Core | Sensitive directory hard blacklist and system asset protection guard — src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/sensitive_blacklist.py [INPUT] pathlib, os, myrm_agent_harness.core.security.scoped_folder_sandbox_mount.types [OUTPUT] SensitivePathGuard | ✅ |
| types.py | Core | Type definitions for Scoped Folder Permission Dialog and Sandbox Dynamic Mount Suite — src/myrm_agent_harness/core/security/scoped_folder_sandbox_mount/types.py [INPUT] enum, dataclasses [OUTPUT] FolderAccessMode, MountLifecyclePolicy, ScopedFolderGrant, SensitivePathCheckResult, DynamicMountSpec | ✅ |
