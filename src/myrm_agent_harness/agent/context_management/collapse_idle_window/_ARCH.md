# collapse_idle_window/

## Overview

Stream windowing subsystem enforcing causal collapse-before-cut sequencing to prevent compression distortion and protect tail action history from being evicted by consecutive idle runs.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Collapse-idle-before-cut stream windowing subsystem package entry point. | ✅ |
| `collapse_idle_types.py` | Types | Domain contracts, stream step models, and audit receipts for idle windowing. | ✅ |
| `collapse_window_cut_engine.py` | Core | Pipeline engine enforcing collapse-before-cut causal sequencing on stream steps. | ✅ |
| `headlong_collapse_idle_suite.py` | Core | Unified facade suite managing stream noise pruning, idle collapsing, and window cut. | ✅ |
| `idle_stream_collapser.py` | Core | Stream pruning and consecutive idle/error step collapsing engine. | ✅ |
