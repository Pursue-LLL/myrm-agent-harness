# computer_use/recording/

## Overview
Desktop workflow skill recording, capture driving, event clustering, Tool Lifting (GUI-to-code/CLI elevation), and automated `SKILL.md` synthesis.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports recording types, synthesizer functions and the capture driver | ✅ |
| `types.py` | Core | `DesktopRecordedEvent`, `SynthesizedSkillStep`, `SynthesizedSkillDraft`, `ToolLiftingCandidate`. `DesktopRecordedEvent.to_dict()` masks a password value as `***` | ✅ |
| `synthesizer.py` | Core | Pure algorithm for event debouncing, tool lifting, variable extraction, and SKILL.md rendering. A password event's value is dropped from step parameters so a secret can never reach the published SKILL.md; lifted tools name real registry tools (`bash_code_execute_tool`, `file_write_tool`) | ✅ |
| `capture_driver.py` | Core | `DesktopCaptureDriver` polls foreground AX snapshots, diffs consecutive frames via `perception/ax_diff`, and emits `DesktopRecordedEvent` interactions (click / type / window_focus). A secure-role element (`dref.types.is_secure_role`) yields a type event with no value and `is_password=True` | ✅ |

## Security contracts

- **Secure fields**: macOS reports a password field with role `AXTextField`; **only the subrole (`AXSecureTextField`) distinguishes it**, so the AppleScript snapshot resolves the secure role *before* the `value` read and skips that read entirely. The value therefore never leaves the accessibility tree — the guarantee does not depend on masking after the fact, and it also closes the `ElementRef.name or value` fallback path. `is_secure_role` is the single predicate; `overlay_roles.normalize_desktop_role` maps those roles to `SECURE_OVERLAY_ROLE` so the driver classifies a password entry as a *type* event with no value and `is_password=True`.
- **Sensitive apps**: the same `computer_use.safety.is_sensitive_app` guard as the semantic desktop path; a blocked app re-baselines instead of diffing so returning to a safe app does not replay the blocked window's elements.

## Deliberate scope boundary: no native event tap

Capture is **poll + AX-diff**, not a native input hook (`CGEventTap` / `SetWindowsHookEx` / `XRecord`). This is a considered decision, not an omission:

1. **A native input tap needs a second TCC permission** (`Input Monitoring`, separate from the `Accessibility` grant this feature already requires). Requiring two grants makes a working flow fail for users who stop after the first one.
2. **A system-wide tap widens the privacy surface far beyond AX diffing**: it observes every keystroke in every application, including secrets typed into non-secure fields. That directly contradicts the secure-field redaction above, which relies on never reading a value that need not be read.
3. **Most hotkey effects are already observable**: a hotkey that changes app state adds or updates AX elements, which the diff reports as interactions. The residual gap is a *silent* action (e.g. a save with no visible change), which is not worth the two costs above.

Consequence to state honestly: a pure window move/resize and a silent shortcut are **not** recorded, and a recorded step stores no keystroke. Revisit only if a future platform offers per-app input monitoring without a second system-wide grant.
