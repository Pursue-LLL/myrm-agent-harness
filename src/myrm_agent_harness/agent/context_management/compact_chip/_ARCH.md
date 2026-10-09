# compact_chip/

## Overview
Compact-before-send token chip presentation, preflight context pressure estimation, and honest send action specifications.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports compact chip types, preflight calculator, label renderer, and facade suite. | — |
| `compact_before_send_suite.py` | Core | Master facade coordinating preflight metrics and composer action metadata. | ✅ |
| `compact_chip_types.py` | Types | Domain models, verdicts, preference enums, preflight estimates, and button specs. | — |
| `compact_preflight_calculator.py` | Core | Evaluates context occupancy, staleness, and resolves compaction triggers. | ✅ |
| `send_action_label_renderer.py` | Core | Formats token representations and renders honest send labels and chip tooltips. | ✅ |
