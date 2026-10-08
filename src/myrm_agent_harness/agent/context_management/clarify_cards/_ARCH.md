# clarify_cards/

## Overview

Interactive clarification cards subsystem managing questions, options, user answers, expiration timeouts, and automatic connection-change invalidation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Clarification cards subsystem package entry point and facade exports. | ✅ |
| `clarify_card_engine.py` | Core | Clarification cards lifecycle state machine and registry engine. | ✅ |
| `clarify_card_types.py` | Types | Domain contracts, question payload models, and verification receipts. | ✅ |
| `hermes_desktop_clarify_suite.py` | Core | Unified facade suite managing rendering, answering, expiration, and input interception. | ✅ |
