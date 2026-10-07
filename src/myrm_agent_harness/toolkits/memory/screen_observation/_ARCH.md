# Screen Observation Memory Anti-Injection and Descriptive Fact Gate Architecture

## 1. Positioning and Boundaries
The `screen_observation` module in `myrm-agent-harness` provides desktop/screen memory boundary defense, inspired by ChatGPT Desktop's SkysightSummarizer:

- **Untrusted Observation Evidence Boundary**: Isolates passive visual observations (AX tree, OCR, screenshot summaries) within strict `<observed_visual_evidence>` boundaries and tags them as pure evidence, never instructions.
- **Descriptive-Only Grammar Validator**: Evaluates extracted statements, rejects or rewrites imperative commands ("Do X", "Run Y") into objective third-person descriptive facts ("The user used X").
- **Anti-Overpromotion Gate**: Prevents single-occurrence or ephemeral actions from polluting stable long-term user preferences; requires cross-session verification.
- **Single-Machine Sandbox**: Pure framework toolkit running locally inside the agent execution loop without multi-tenant baggage.

## 2. Component Structure
- `types.py`: Strict domain contracts and data models (`ObservationPayload`, `SanitizedObservationEvidence`, `DescriptiveFactCandidate`, `OverpromotionGateResult`, `ScreenSafetyAuditRecord`).
- `boundary.py`: Semantic boundary fence and prompt injection detector (`UntrustedObservationEvidenceBoundary`).
- `validator.py`: Grammar checker and converter for descriptive-only memory facts (`DescriptiveFactValidator`).
- `gate.py`: Multi-session frequency and overpromotion prevention gatekeeper (`AntiOverpromotionGate`).
- `manager.py`: Integrated facade pipeline orchestrating sanitization, validation, and promotion (`ScreenObservationMemoryManager`).
