# ltra/

## Overview
Listen-Translate-Remember-Act (LTRA) cognitive pipeline toolkit. Distills structured quadruple facts ([subject] [demand] [commitment] [blocker]) from multi-speaker diarized conversation segments, binds immutable verbatim audio timestamp anchors, resolves speaker aliases, enforces commercial confidentiality guards, and constructs actionable sandbox task blueprints.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | LTRA cognitive component package facade. | — |
| `models.py` | Core | Typed contracts for diarized segments, audio anchors, cognitive facts, and followup task drafts. | ✅ |
| `identity_resolver.py` | Core | SpeakerIdentityResolver — acoustic ID to human business role mapping with heuristic mining. | ✅ |
| `guard.py` | Core | SensitiveAudioFactGuard — commercial confidential pricing and PII disclosure filtering. | ✅ |
| `distillation_worker.py` | Core | AudioFactDistillationWorker — noise filtering and structured quadruple fact distillation. | ✅ |
| `task_builder.py` | Core | FollowupTaskDraftBuilder — sandbox task blueprint synthesis and idempotency token calculation. | ✅ |
