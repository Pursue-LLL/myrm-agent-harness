# Engineering Decision Lineage State Machine & Priority Recall Architecture

## Overview
This package implements the `EngineeringDecisionLineageStateMachineAndStructuredPriorityRecallSuite` (Item 72), modeling architectural decisions as stateful entities rather than transient unstructured text.

## Core Modules

| Module | Responsibility | Line Count Target |
| :--- | :--- | :--- |
| `models.py` | Data contracts: `DecisionRecord`, `DecisionStatus`, `PendingDecisionCandidate`, `DecisionRecallHit` | < 150 |
| `noise_filter.py` | `IngestionNoiseFilter`: Filters system instructions, context boundaries, and prompt injection bloat | < 150 |
| `lineage.py` | `DecisionLineageEngine`: Manages `active -> superseded -> discarded` lifecycle and acyclic DAG validation | < 200 |
| `reranker.py` | `StructuredPriorityReranker`: Jaccard-0.8 dedup, MMR diversity, ChronoRank aging penalty, and metacognitive boundary | < 250 |
| `db.py` | `DecisionDatabase`: SQLite WAL storage, DDL, busy timeouts, and serialized transactions | < 350 |
| `store.py` | `EngineeringDecisionStore`: High-level operational facade coordinating validation, staging, and recall | < 300 |
| `tool.py` | `RecordArchitectureDecisionTool`: Model meta-tool interface exposing decision staging and confirmation gate | < 180 |
| `__init__.py` | Package facade for decisions. | — |

## Design Principles
- **Decisions as State**: Decisions hold explicit lifecycle status with parent-child supersession lineage (`supersedes_id`, `superseded_by`).
- **Confirmation Gate**: Candidates stage in a pending buffer awaiting human or policy approval before becoming active.
- **Structured Priority**: Decisions matching queries with overlap >= 0.5 are boosted to the top of prompt sections.
- **Zero-Any Type Safety**: All interfaces strictly type-annotated conforming to Myrm Harness guidelines.
