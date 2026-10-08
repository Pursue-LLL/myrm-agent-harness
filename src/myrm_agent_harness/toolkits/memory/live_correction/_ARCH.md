# Natural Language Memory Feedback and Live Correction Suite Architecture

## 1. Positioning and Boundary
- **Layer**: `myrm-agent-harness` core memory framework module.
- **Responsibility**: In-conversation natural language memory feedback detection, conflict localization, atomic state mutation (supersede, retract, amend, create novel), and human-friendly receipt formatting.
- **No Multi-tenancy**: Strictly standalone/single-user execution engine. No business server or control-plane coupling.

## 2. Components
1. `NaturalLanguageCorrectionDetector`: Rule-based deterministic extractor for Chinese/English conversational correction utterances.
2. `CorrectionTargetLocalizer`: Semantic matching engine identifying existing conflicting or outdated memory candidates.
3. `AtomicMemoryMutator`: Atomic state transition operator creating immutable supersession and retraction lineage records.
4. `LiveCorrectionOrchestrator`: End-to-end pipeline orchestrating detection, localization, mutation, and acknowledgement text synthesis.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Natural language live memory correction and feedback package. | ✅ |
| `detector.py` | Core | Natural language correction detector extracting semantic slots from conversational utterances. | ✅ |
| `localizer.py` | Core | Target node semantic localizer identifying existing memory candidates for live correction. | ✅ |
| `models.py` | Types | Domain models and contracts for natural language memory feedback and live correction. | ✅ |
| `mutator.py` | Core | Atomic memory mutator executing live corrections and version lineage management. | ✅ |
| `orchestrator.py` | Core | Live correction orchestrator coordinating detection, localization, mutation, and acknowledgement. | ✅ |
