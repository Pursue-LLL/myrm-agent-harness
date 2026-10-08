# core/security/asr_privacy_tradeoff/

## Overview
ASR voice transcription privacy controller enforcing transparent tradeoffs between transcript retention and speaker embedding reuse.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade exporting AsrPrivacyTradeoffController, policies, and result types. | — |
| `types.py` | Types | Domain models for transcription requests, retention policies, and tradeoff evaluations. | ✅ |
| `controller.py` | Core | Evaluation engine validating audio lifecycle, speaker embedding retention, and privacy notices. | ✅ |

## Dependencies
- Standard library: `dataclasses`, `enum`
- No internal harness coupling.
