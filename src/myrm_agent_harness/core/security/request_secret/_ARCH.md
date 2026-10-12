# request_secret/

## Overview

Request-Secret Masked Credential Card Suite. src/myrm_agent_harness/core/security/request_secret/__init__.py Request-Secret Masked Credential Card Suite. Exports domain types, session manager, sanitizer, and facade. Strict typing applied: No `Any` types allowed.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Request-Secret Masked Credential Card Suite — src/myrm_agent_harness/core/security/request_secret/__init__.py Request-Secret Masked Credential Card Suite. Exports domain types, session manager, sanitizer, and facade. Strict typing applied: No `Any` types allowed. | ✅ |
| card_manager.py | Core | Lifecycle manager for secret request card sessions, masked credential registry, and fulfillment verification — src/myrm_agent_harness/core/security/request_secret/card_manager.py [INPUT] time, uuid, typing, types, sanitizer [OUTPUT] SecretCardSessionManager Lifecycle manager for secret request card sessions, masked credential registry, and fulfillment verification. Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade for request_secret cards, masked backfills, and transcript-safe secret injection — src/myrm_agent_harness/core/security/request_secret/facade.py [INPUT] typing, types, card_manager, sanitizer [OUTPUT] RequestSecretMaskedCredentialCardFacade Unified facade for request_secret cards, masked backfills, and transcript-safe secret injection. Strict typing applied: No `Any` types allowed. | ✅ |
| sanitizer.py | Core | Sanitizer for secret submissions enforcing field whitelisting, mask generation, and incomplete target rejection — src/myrm_agent_harness/core/security/request_secret/sanitizer.py [INPUT] typing, types [OUTPUT] IncompleteCredentialError, SecretPayloadSanitizer Sanitizer for secret submissions enforcing field whitelisting, mask generation, and incomplete target rejection. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | SecretCardSession, SecretInputSubmission, SanitizedSecretResult — src/myrm_agent_harness/core/security/request_secret/types.py [INPUT] enum, typing, pydantic [OUTPUT] SecretRequestStatus, MaskedCredentialRef, SecretRequestIntent, SecretCardSession, SecretInputSubmission, SanitizedSecretResult Domain types for Request-Secret Masked Credential Card Suite. Strict typing applied: No `Any` types allowed. | ✅ |
