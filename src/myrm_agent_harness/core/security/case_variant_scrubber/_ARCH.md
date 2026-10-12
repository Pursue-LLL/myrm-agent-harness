# case_variant_scrubber/

## Overview

Exports for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite. src/myrm_agent_harness/core/security/case_variant_scrubber/__init__.py [INPUT] facade, types, case_folded_scrubber, oauth_pkce_seam [OUTPUT] Public API exports Exports for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Exports for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite — src/myrm_agent_harness/core/security/case_variant_scrubber/__init__.py [INPUT] facade, types, case_folded_scrubber, oauth_pkce_seam [OUTPUT] Public API exports Exports for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite. | ✅ |
| case_folded_scrubber.py | Core | Implements canonical case-folding and delimiter normalization for environment variables — src/myrm_agent_harness/core/security/case_variant_scrubber/case_folded_scrubber.py [INPUT] fnmatch, logging, time, typing [OUTPUT] CaseFoldedCredentialScrubber Implements canonical case-folding and delimiter normalization for environment variables. Defends subprocesses against case-variant credential leakage (e.g. Openai_Api_Key, github_Token). Strict typing applied: No `Any` types allowed. | ✅ |
| facade.py | Core | Unified facade for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite — src/myrm_agent_harness/core/security/case_variant_scrubber/facade.py [INPUT] typing [OUTPUT] CaseVariantScrubberSuite Unified facade for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite. Strict typing applied: No `Any` types allowed. | ✅ |
| oauth_pkce_seam.py | Core | Implements declarative OAuth 2.0 PKCE authentication flow seam according to RFC 7636 — src/myrm_agent_harness/core/security/case_variant_scrubber/oauth_pkce_seam.py [INPUT] base64, hashlib, logging, secrets, threading, time, urllib.parse, uuid [OUTPUT] OAuthPKCESeam Implements declarative OAuth 2.0 PKCE authentication flow seam according to RFC 7636. Supports external AI model provider registration, browser challenge URLs, and code exchange validation. Strict typing applied: No `Any` types allowed. | ✅ |
| types.py | Core | Data structures and specifications for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite — src/myrm_agent_harness/core/security/case_variant_scrubber/types.py [INPUT] dataclasses, enum, typing [OUTPUT] ScrubActionEnum, OAuthPKCEChallengeMethod, ScrubbedEnvRecord, ScrubAuditReport, OAuthPKCEState, OAuthProviderManifest, ScrubberSuiteMetrics Data structures and specifications for Case-Variant Credential Scrubbing & Declarative OAuth PKCE Provider Seam Suite. Strict typing applied: No `Any` types allowed. | ✅ |
