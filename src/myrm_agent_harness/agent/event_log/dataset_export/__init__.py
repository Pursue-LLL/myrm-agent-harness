"""Dataset Export — convert execution traces to standard fine-tuning formats.

Provides a pipeline to export event log data as ShareGPT, Alpaca, or
OpenAI JSONL datasets, with built-in PII redaction, quality filtering,
and content deduplication.

[INPUT]
- event_log.trace_builder::build_trace, query_traces (POS: Read-side aggregation logic)
- event_log.protocols::EventLogBackend (POS: Protocol contract)
- security.detection.pii_redactor::redact_pii (POS: PII redactor)

[OUTPUT]
- DatasetExporter: orchestrator for the full export pipeline
- ExportFormat: supported output formats
- ExportConfig: export parameters
- ExportReport: summary of an export run

[POS]
Dataset export pipeline. Pure additive module — reads existing event logs
and writes JSONL files without modifying any existing code paths.
"""

from .exporter import DatasetExporter
from .protocols import ExportConfig, ExportFormat, ExportReport

__all__ = [
    "DatasetExporter",
    "ExportConfig",
    "ExportFormat",
    "ExportReport",
]
