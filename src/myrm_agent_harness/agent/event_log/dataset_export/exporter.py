"""Dataset exporter — orchestrates the full export pipeline.

Coordinates trace retrieval, quality filtering, PII redaction,
deduplication, format conversion, and JSONL file writing.

Supports incremental export via a state file that tracks the last
exported session IDs, avoiding re-processing on subsequent runs.

[INPUT]
- event_log.protocols::EventLogBackend (POS: Protocol contract)
- event_log.trace_builder::build_trace (POS: Read-side aggregation logic)
- dataset_export.quality_filter::passes_quality (POS: Stateless quality gate)
- dataset_export.format_converter (POS: Stateless format conversion)
- dataset_export.protocols::ExportConfig, ExportReport (POS: Pure type definitions)

[OUTPUT]
- DatasetExporter: async orchestrator class

[POS]
Pipeline orchestrator. Streams traces one-by-one to bound memory usage.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..trace_builder import build_trace
from .format_converter import convert_trace, deduplicate, redact_trace_pii
from .protocols import ExportConfig, ExportFormat, ExportReport
from .quality_filter import passes_quality

logger = logging.getLogger(__name__)


class DatasetExporter:
    """Orchestrates dataset export from event logs to JSONL files.

    Usage::

        from myrm_agent_harness.agent.event_log.dataset_export import (
            DatasetExporter, ExportConfig, ExportFormat,
        )

        exporter = DatasetExporter(backend)
        report = await exporter.export(ExportConfig(
            output_dir=Path("./exports"),
            formats=(ExportFormat.SHAREGPT, ExportFormat.OPENAI),
            max_samples=1000,
        ))
        print(report.to_dict())
    """

    def __init__(self, backend: object) -> None:
        """Initialize with an EventLogBackend instance.

        Args:
            backend: must satisfy the EventLogBackend protocol
        """
        from ..protocols import EventLogBackend

        if not isinstance(backend, EventLogBackend):
            raise TypeError(f"Expected EventLogBackend, got {type(backend).__name__}")
        self._backend = backend

    async def export(self, config: ExportConfig) -> ExportReport:
        """Run the full export pipeline.

        Pipeline stages:
        1. Enumerate sessions (optionally incremental)
        2. Build traces one-by-one (stream, not batch)
        3. Quality filter
        4. PII redaction (if enabled)
        5. Format conversion
        6. Deduplication
        7. Write JSONL files

        Args:
            config: export parameters

        Returns:
            ExportReport with pipeline statistics.
        """
        start_time = time.monotonic()
        report = ExportReport()

        try:
            session_ids = await self._backend.get_all_session_ids()
            report.total_sessions_scanned = len(session_ids)

            if not session_ids:
                report.duration_ms = (time.monotonic() - start_time) * 1000
                return report

            previously_exported = _load_incremental_state(config.incremental_state_file)
            if previously_exported:
                session_ids = [sid for sid in session_ids if sid not in previously_exported]
                if not session_ids:
                    logger.info("All sessions already exported (incremental)")
                    report.duration_ms = (time.monotonic() - start_time) * 1000
                    return report

            samples_by_format: dict[ExportFormat, list[dict[str, object]]] = {
                fmt: [] for fmt in config.formats
            }

            exported_session_ids: list[str] = []

            for sid in session_ids:
                if config.max_samples > 0 and report.traces_passed_quality >= config.max_samples:
                    break

                try:
                    trace = await build_trace(self._backend, sid)
                except Exception as exc:
                    report.errors.append(f"session={sid}: {exc!r}")
                    continue

                if config.start_time and trace.start_time < config.start_time:
                    continue
                if config.end_time and trace.start_time > config.end_time:
                    continue

                if not passes_quality(trace, config.quality):
                    continue

                report.traces_passed_quality += 1

                if config.redact_pii:
                    trace, redaction_count = redact_trace_pii(trace)
                    report.pii_redactions += redaction_count

                for fmt in config.formats:
                    sample = convert_trace(trace, fmt)
                    samples_by_format[fmt].append(sample)

                exported_session_ids.append(sid)

            config.output_dir.mkdir(parents=True, exist_ok=True)

            for fmt, samples in samples_by_format.items():
                before_dedup = len(samples)
                samples = deduplicate(samples)
                report.traces_deduplicated += before_dedup - len(samples)

                if not samples:
                    continue

                output_file = config.output_dir / f"dataset_{fmt.value}.jsonl"
                _write_jsonl(output_file, samples)
                report.output_files.append(str(output_file))

            report.samples_exported = report.traces_passed_quality - report.traces_deduplicated

            if config.incremental_state_file and exported_session_ids:
                all_exported = previously_exported | set(exported_session_ids)
                _save_incremental_state(config.incremental_state_file, all_exported)

        except Exception as exc:
            report.errors.append(f"pipeline: {exc!r}")
            logger.exception("Dataset export pipeline failed")

        report.duration_ms = (time.monotonic() - start_time) * 1000
        return report


# ---------------------------------------------------------------------------
# Incremental state persistence
# ---------------------------------------------------------------------------


def _load_incremental_state(state_file: Path | None) -> set[str]:
    """Load previously exported session IDs from state file."""
    if not state_file or not state_file.exists():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return set(data.get("exported_sessions", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_incremental_state(state_file: Path, exported: set[str]) -> None:
    """Persist exported session IDs for incremental tracking."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"exported_sessions": sorted(exported)}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_jsonl(output_file: Path, samples: list[dict[str, object]]) -> None:
    """Write samples as JSONL, one JSON object per line."""
    with output_file.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    logger.info("Wrote %d samples to %s", len(samples), output_file)
