# Person Card and Relationship Memory Layer Architecture

## Overview
The Person Card and Relationship Memory Layer bridges the structural gap in personal AI agents where memory previously only tracked the user and project artifacts. It provides structured representation of related people (friends, colleagues, clients, vendors), tracks preferences (dietary restrictions, timezone, birthday, approval habits), maintains interaction recency through continuous gravity decay, and performs pre-action attribute verification to prevent embarrassing mistakes prior to outbound actions (invites, emails, delegations, approvals).

## Components

| File | Type | Description |
|---|---|---|
| `models.py` | Data Models | Domain models including `PersonCard`, `PersonAttributes`, `RelationType`, `ActionType`, and `PreActionCheckResult`. |
| `person_card_store.py` | Store & Index | Persistence, alias matching, gravity decay score recalculation (`weak` memory status), and profile merging. |
| `pre_action_checker.py` | Proactive Gate | Evaluates participant critical attributes prior to outbound actions and generates prompt cues. |
| `__init__.py` | Facade | Public package API exports. |

## Data Flow
```
[User Input / Distillation / vCard]
              │
              ▼
       PersonCardStore
              │
   ┌──────────┴──────────┐
   ▼                     ▼
Gravity Decay       PreActionAttributeChecker
(Active/Weak)            │
                         ▼
             [PreActionCheckResult]
             (Prompt Cue & Missing Attr Warning)
```
