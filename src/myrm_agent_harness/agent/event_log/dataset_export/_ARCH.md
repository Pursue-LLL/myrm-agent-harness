# dataset_export/

## Overview
Export pipeline — convert ExecutionTrace into standard fine-tuning datasets (ShareGPT / Alpaca / OpenAI JSONL) with PII redaction, quality filtering, content deduplication, and incremental export support.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports DatasetExporter, ExportConfig, ExportFormat, ExportReport | ✅ |
| protocols.py | Config | ExportFormat, ExportConfig, QualityThresholds, ExportReport type definitions | ✅ |
| quality_filter.py | Core | 3-dimension quality gate (task outcome, conversation depth, content integrity) | ✅ |
| format_converter.py | Core | 3-format conversion (ShareGPT/Alpaca/OpenAI), SHA-256 dedup, PII redaction | ✅ |
| exporter.py | Core | DatasetExporter async orchestrator — streams traces, writes JSONL, tracks incremental state | ✅ |

## Key Dependencies

- `event_log.trace_builder` — build_trace for trace construction
- `event_log.protocols` — EventLogBackend protocol
- `security.detection.pii_redactor` — redact_pii for PII masking
