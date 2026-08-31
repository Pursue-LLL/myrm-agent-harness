# metrics/

## Overview
Metrics export module. Supports Prometheus, OTLP, Console, and other exporters.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Metrics export module. Supports Prometheus, OTLP, Console, and other exporters. | ✅ |
| cardinality.py | Core | Metrics cardinality control. Maintains an LRU cache for high-frequency entities and aggregates low-f | ✅ |
| collector.py | Core | Simplified metrics collection with automatic trace_id labeling. | ✅ |
| exporter.py | Core | Metrics exporter configuration. Provides Console and OTLP export, plus `is_metrics_initialized()` posture probe. | ✅ |
| meter.py | Core | Meter provider. Wraps OpenTelemetry Meter acquisition logic. | ✅ |
