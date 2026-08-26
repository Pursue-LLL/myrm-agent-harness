# computer_use/recording/

## Overview
Desktop workflow skill recording, event clustering, Tool Lifting (GUI-to-code/CLI elevation), and automated `SKILL.md` synthesis.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports recording types and synthesizer functions | ✅ |
| `types.py` | Core | `DesktopRecordedEvent`, `SynthesizedSkillStep`, `SynthesizedSkillDraft`, `ToolLiftingCandidate` | ✅ |
| `synthesizer.py` | Core | Pure algorithm for event debouncing, tool lifting, variable extraction, and SKILL.md rendering | ✅ |
