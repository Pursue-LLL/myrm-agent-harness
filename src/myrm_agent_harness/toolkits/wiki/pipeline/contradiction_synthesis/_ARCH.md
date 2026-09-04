# contradiction_synthesis/

## Overview

Compile-time Contradiction Synthesis Pass (CCSP). After a compile batch generates concept
articles, detects cross-concept factual conflicts and stages `Comparisons/.../Evolution`
comparison pages through the existing HITL pending queue.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package marker for contradiction synthesis. | ✅ |
| `types.py` | Types | ConceptPair, ConflictVerdict, SynthesisPassResult | ✅ |
| pairing.py | Core | Zero-LLM pair prefilter (canonical, related, slug, vault) | ✅ |
| detector.py | Core | Structured LLM conflict verdict — parsed via `parse_llm_json_object` (robust against fences, prose, bare control chars, trailing commas) | ✅ |
| writer.py | Core | Evolution page markdown + metadata (`Comparisons/.../Evolution`); CJK topic → Chinese body | ✅ |
| backlink.py | Core | Post-approve timeline backlinks on linked concepts | ✅ |
| service.py | Core | `run_contradiction_synthesis_pass` orchestrator | ✅ |

## Key Dependencies

- `pipeline/pending.py` — HITL staging
- `toolkits/wiki/core/canonical_registry.py` — pairing signals
- Replaces dead `maintenance/linter._check_consistency` path
