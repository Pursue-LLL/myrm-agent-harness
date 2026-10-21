# metrics/

## Overview
Metrics export module. Supports Prometheus, OTLP, Console, and other exporters.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Metrics export module. Supports Prometheus, OTLP, Console, and other exporters. | ✅ |
| cardinality.py | Core | Metrics cardinality control. Maintains DynamicLabelManager for entity aggregation, and CardinalityFirewall (sanitize_metric_labels) for stripping unbounded high-cardinality keys. | ✅ |
| collector.py | Core | Simplified metrics collection with automatic CardinalityFirewall label sanitization. | ✅ |
| exporter.py | Core | Metrics exporter configuration. Provides Console and OTLP export, pure-python VCS Git resource injection, and 1500ms bounded force-flush and shutdown. | ✅ |
| meter.py | Core | Meter provider. Wraps OpenTelemetry Meter acquisition logic. | ✅ |
