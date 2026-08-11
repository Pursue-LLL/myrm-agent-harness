# cognitive/

## Overview
Cognitive memory consolidation layer.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Cognitive memory consolidation layer. | — |
| consolidator.py | Core | @input: MemoryManager | ✅ |
| deriver.py | Core | Cognitive Deriver — async dialectic reasoning for implicit user preferences (Claim Graph). Parses the derived-preference array via `parse_llm_json_list` (robust against fences, prose, bare control chars, trailing commas). | ✅ |
