# Architecture Contract: Experience Compounding & Knowledge Condensation Suite

## 1. Context & Purpose
Traditional memory systems accumulate observations in an append-only fashion, causing information entropy to explode.
Without frequency reinforcement and semantic synthesis:
1. Micro-fragments (e.g. slight indentation, naming style, specific quirks) scatter across multiple memories, diluting prompt attention and wasting tokens.
2. Temporary task contexts (e.g. one-off debugging sessions, expired deadlines) linger in the active retrieval pool forever.
3. Proven principles lack compounding mechanisms, competing equally with unverified transient notes.

The `ExperienceCompoundingAndKnowledgeCondensationSuite` establishes a self-evolving knowledge flywheel:
- **Frequency-Driven Compounding**: Enhances verified memories using a bounded logarithmic compounding formula.
- **Semantic Knowledge Condensation**: Synthesizes clusters of fragmented memories into structured Golden Rules with parent-child lineage.
- **Obsolete Context Annealing**: Smoothly tier-deprecates one-off temporary contexts to cold storage while honoring active leases.

## 2. Invariants & Guardrails
- **Bounded Compounding**: Weight growth is capped at $W_{max}=2.5$ to prevent Matthew effect dominance.
- **Non-Destructive Lineage**: Condensation archives original fragments (`CONDENSED_ARCHIVED`) and records `source_fragment_ids` on the Golden Rule. Physical destruction is forbidden.
- **Active Lease Protection**: Contexts marked as `in_progress`, `pinned`, or `active_task` are strictly exempt from annealing decay.
- **Type Safety & Decoupling**: Pure typed abstractions without `Any`. Zero private/deep imports into external application layers.
