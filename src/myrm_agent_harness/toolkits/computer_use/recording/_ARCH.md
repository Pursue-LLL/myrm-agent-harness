# computer_use/recording/

## Overview
Desktop workflow skill recording, capture driving, event clustering, Tool Lifting (GUI-to-code/CLI elevation), and automated `SKILL.md` synthesis.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports recording types, synthesizer functions and the capture driver | ✅ |
| `types.py` | Core | `DesktopRecordedEvent`, `SynthesizedSkillStep`, `SynthesizedSkillDraft`, `ToolLiftingCandidate` | ✅ |
| `synthesizer.py` | Core | Pure algorithm for event debouncing, tool lifting, variable extraction, and SKILL.md rendering | ✅ |
| `capture_driver.py` | Core | `DesktopCaptureDriver` polls foreground AX snapshots, diffs consecutive frames via `perception/ax_diff`, and emits `DesktopRecordedEvent` interactions (click / type / window_focus) | ✅ |
