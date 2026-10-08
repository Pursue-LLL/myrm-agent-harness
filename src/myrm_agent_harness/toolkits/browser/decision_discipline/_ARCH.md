# decision_discipline/

## Overview

Subsystem providing explicit browser next-step decision discipline rulebooks, pre-flight action guards, target selection validators, and single-key text generation output contracts. Prevents four frequent browser agent failures: redundant steps/toggles, premature form submission without required fields, abusive WAIT loops misinterpreting historical WAITs as loading evidence, and unsubstantiated early DONE declarations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Browser decision discipline package entry point. | ✅ |
| `browser_decision_discipline_suite.py` | Facade | Unified orchestration facade managing prompts, pre-flight guards, and output contracts. | ✅ |
| `decision_discipline_types.py` | Types | Domain models, element states, verdicts, and configuration thresholds. | ✅ |
| `next_step_decision_rulebook.py` | Core | Decision discipline prompt rulebooks and programmatic action/target validation guards. | ✅ |
| `text_output_contract.py` | Core | Single-key `{"text": ...}` text generation prompt and strict parser validator. | ✅ |
