# vnc_hardening/

## Overview

VNC Loopback Bind and Rfbauth Hardening Suite. src/myrm_agent_harness/core/security/vnc_hardening/__init__.py VNC Loopback Bind and Rfbauth Hardening Suite. Exports domain types, config sanitizer, password manager, and facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | VNC Loopback Bind and Rfbauth Hardening Suite — src/myrm_agent_harness/core/security/vnc_hardening/__init__.py VNC Loopback Bind and Rfbauth Hardening Suite. Exports domain types, config sanitizer, password manager, and facade. Strict typing applied: No `Any` types allowed. | ✅ |
| config_sanitizer.py | Core | Sanitizer for x11vnc launch arguments enforcing -localhost default, -nopw removal, and rfbauth — src/myrm_agent_harness/core/security/vnc_hardening/config_sanitizer.py [INPUT] typing, types, passwd_manager [OUTPUT] VncLaunchConfigSanitizer Sanitizer for x11vnc launch arguments enforcing -localhost default, -nopw removal, and rfbauth. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade for VNC loopback bind enforcement and rfbauth authentication hardening — src/myrm_agent_harness/core/security/vnc_hardening/facade.py [INPUT] time, typing, types, config_sanitizer, passwd_manager [OUTPUT] VncLoopbackBindAndRfbauthHardeningFacade Unified facade for VNC loopback bind enforcement and rfbauth authentication hardening. Strict typing applied: No `Any` types allowed. | ✅ |
| passwd_manager.py | Core | VNC credential and password manager enforcing rfbauth complexity and file permission sandboxing — src/myrm_agent_harness/core/security/vnc_hardening/passwd_manager.py [INPUT] os, secrets, string, stat, pathlib, typing [OUTPUT] VncSecurityException, VncPasswdManager VNC credential and password manager enforcing rfbauth complexity and file permission sandboxing. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | VncLaunchConfig, VncHardenedLaunchSpec, VncHardeningAuditReport — src/myrm_agent_harness/core/security/vnc_hardening/types.py [INPUT] enum, typing, pydantic [OUTPUT] VncBindMode, VncAuthPolicy, VncSecurityViolationType, VncSecurityAuditViolation, VncLaunchConfig, VncHardenedLaunchSpec, VncHardeningAuditReport Core domain types for VNC loopback bind and rfbauth hardening suite. Strict typing applied: No `Any` types allowed. | ✅ |
