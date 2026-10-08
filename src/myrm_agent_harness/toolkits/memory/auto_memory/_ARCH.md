# [POS]: myrm_agent_harness.toolkits.memory.auto_memory
# [INPUT]: Conversation transcripts, session activity telemetry, token budget metrics
# [OUTPUT]: AutoMemoryGate, SixDimensionalExtractor, IdleAndBudgetGatedAutoMemoryEngine, SixDimensionalMemorySlice

## Module Architecture: Idle and Budget Gated Auto-Memory Engine Suite (Item 123)

### Responsibilities
1. **Idle-Timeout Detection**: Evaluates whether a session has been inactive long enough (e.g. 15 minutes) to warrant background consolidation without user intervention.
2. **Turn-Count Gate**: Skips short interactions (< 3 turns) or trivial Q&A to prevent polluting the persistent memory store with low-utility fragments ("dialogue too short, don't record").
3. **Token Budget Gate**: Aborts or suspends consolidation if the session or global token budget is exhausted, preventing background memory extraction from becoming a billing burden ("quota gone, don't record").
4. **Six-Dimensional Structured Artifact**: Extracts structured knowledge facets instead of raw text blobs:
   - `workspace_env`: Target repository, working directory, language/tooling environment.
   - `key_topics`: Domain terminology and high-level themes.
   - `user_preferences`: Explicit and implicit user constraints, styles, and guidelines.
   - `reusable_knowledge`: Modular patterns, reusable functions, domain facts.
   - `failure_lessons`: Anti-patterns, resolved pitfalls, bug post-mortems.
   - `tool_habits`: Frequently used tools, parameters, invocation sequences.

### Hierarchy & Clean Architecture
- Pure stateless gating logic in `gate.py`.
- Deterministic heuristic and prompt extraction in `extractor.py`.
- Unified state machine and entrypoint in `engine.py`.
- Strict typing, zero `Any`, frozen domain models in `models.py`.
