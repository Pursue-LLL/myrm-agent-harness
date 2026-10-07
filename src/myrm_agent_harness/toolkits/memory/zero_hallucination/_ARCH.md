# Zero-Hallucination & Explicit State Memory Protocol Architecture

## Overview
The `zero_hallucination` module establishes a fault-transparent retrieval protocol and anti-fabrication prompt guard for agent memory queries. It completely eliminates silent error-swallowing in storage layers and strictly prevents LLMs from hallucinating past user preferences or historical configurations.

## Architecture & Principles
1. **Explicit Tri-State Assertion**:
   Categorizes memory recall results into explicit, strictly-typed states:
   - `FOUND`: Verified matching historical facts exist and are loaded.
   - `EXPLICIT_EMPTY`: Search executed successfully, but memory store positively confirms zero matching records.
   - `SERVICE_UNAVAILABLE`: Storage engine (vector DB or SQLite) is offline or unreachable; errors are never hidden.
   - `PARTIAL_DEGRADED`: Multi-source retrieval experienced partial engine failures while surviving sources returned facts.
   - `SEARCH_FAILED`: Query syntax or unrecoverable execution errors.
2. **Dual-Anchor Anti-Fabrication Prompt Guard**:
   When memory is `EXPLICIT_EMPTY`, injects negative constraint anchors into LLM context, instructing the model to declare the absence of history and forbidding guessing or extrapolation.
3. **Graceful Degradation Notice**:
   When storage services are offline (`SERVICE_UNAVAILABLE`), transparently alerts the user and guides the model to proceed with conversation reasoning without assuming unretrieved historical rules.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Entry | Package facade re-exporting the retrieval state models, prompt guard and state evaluator. | ✅ |
| `models.py` | Types | Strongly-typed dataclasses and enumerations (`MemoryRetrievalState`, `RetrievalErrorSeverity`, `MemoryFactItem`, `ZeroHallucinationRetrievalResult`). | ✅ |
| `guard.py` | Core | Prompt context wrapper and anti-fabrication directive builder (`ZeroHallucinationPromptGuard`). | ✅ |
| `evaluator.py` | Core | Deterministic state evaluator converting raw store returns and exceptions into defensive assertions (`MemoryStateAssertionEvaluator`). | ✅ |
