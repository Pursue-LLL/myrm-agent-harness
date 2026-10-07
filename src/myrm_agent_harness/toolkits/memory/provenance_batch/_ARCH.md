# provenance_batch/

## Overview
Skill Memory Extraction Provenance Trace Link & Batch Learn Namespace Isolator: anchors extracted procedural rules to physical tool execution traces (ToolExecutionTrace) and turn snippets, and partitions batch learning IDs deterministically ({namespace}::{scope}::{raw_id}) eliminating cross-scope memory leakage and concurrent collision.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Subsystem module providing forensic trace linking and namespaced batch learning. | ✅ |
| `isolator.py` | Core | Guarantees namespace and scope hard boundary isolation during concurrent batch learning pipelines. | ✅ |
| `provenance_linker.py` | Core | Bi-directional trace linking ensuring procedural rules are verifiable against real execution logs. | ✅ |
| `types.py` | Types | Data structures and value objects for skill extraction provenance and batch learning isolation. | ✅ |

## Key Dependencies

- `toolkits.memory`
- External libraries: `pydantic`
