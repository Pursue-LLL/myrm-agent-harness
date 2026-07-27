# loop_suggestions/

## Overview

Suggestion generation subsystem for LoopGuard. Static `TOOL_SUGGESTIONS` in `core.py` plus dynamic generators per tool (web, file, browser snapshot, etc.).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Suggestion generation subsystem for LoopGuard. Analyzes parameters and | ✅ |
| bash.py | Core | Bash tool suggestions for loop detection. | ✅ |
| browser.py | Core | Browser tool suggestions for loop detection. | ✅ |
| core.py | Core | Core functions and static suggestions for loop detection. | ✅ |
| file.py | Core | File tool suggestions for loop detection. | ✅ |
| memory.py | Core | Memory tool suggestions for loop detection. | ✅ |
| meta.py | Core | Meta tool suggestions (subagent, skill) for loop detection. | ✅ |
| web.py | Core | Web tool suggestions for loop detection. | ✅ |
