# fact_supersession/

## Overview

Gate evaluating factual contradictions and routing low-confidence candidates into quarantine.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for fact supersession. | ✅ |
| `contradiction_quarantine.py` | Core | Gate evaluating factual contradictions and routing low-confidence candidates into quarantine. | ✅ |
| `dialectic_retriever.py` | Core | Projector augmenting recalled facts with their historical supersession lineage for explainability. | ✅ |
| `models.py` | Types | Types and models for fact supersession. | ✅ |
| `supersession_chain.py` | Core | Engine managing fact lifecycle, explicit supersession chains, and valid-time interval queries. | ✅ |
