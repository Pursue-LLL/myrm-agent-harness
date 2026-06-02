# auth/

## Overview
Subscription authentication subsystem for external CLI agent backends — lets a
delegated CLI (Codex / Claude Code / Gemini / Qwen …) run on the user's own model
subscription instead of a metered API key. Framework-level mechanisms only; the
business layer drives GUI/SaaS login, status badges, and credential persistence.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public surface of the ACP auth subsystem. | ✅ |
| _profiles.py | Internal | Per-backend auth profiles: credential paths, login command, strategy, api-key env. | ✅ |
| credential_store.py | Core | Detect / import / clear subscription credentials (atomic, owner-only writes). | ✅ |
| login_session.py | Core | Drive `<cli> login` and stream structured AuthEvents (URL/code → SUCCESS/ERROR). | ✅ |

## Design notes
- **Environment-aware paths**: `AuthProfile.resolve_home` honours per-CLI home
  overrides (`CODEX_HOME`, `CLAUDE_CONFIG_DIR`), so the control plane redirects a
  CLI's home to a persistent volume without any change here.
- **Auth never enters the model**: credentials and auth state stay in the backend /
  config layers; they are never injected into prompts or tool descriptions, so the
  prompt prefix cache is unaffected.
- **No runtime hard pre-check**: file-based detection cannot see alternative stores
  (e.g. macOS Keychain), so the runtime never blocks on it pre-emptively. The CLI's
  own not-logged-in error surfaces via `PROCESS_CRASHED`; visibility is delivered by
  status badges (`CredentialStore.state`, `BackendDetector.detect_with_auth`).
- **Import is the universal fallback**: where scripted login is unavailable
  (`scriptable_login` is False) or inconvenient, the user pastes a credential blob
  captured elsewhere and `CredentialStore.import_credential` persists it safely.
