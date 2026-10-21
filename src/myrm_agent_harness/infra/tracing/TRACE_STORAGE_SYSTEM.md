# Trace Storage Integration Guide

> Production-ready guide for exporting traces to Jaeger, Zipkin, or other OTLP-compatible backends.

## Overview

`myrm-agent-harness` uses OpenTelemetry for distributed tracing. The framework provides:

- **Consumer API**: `get_tracer()`, `trace_async()`, `trace_context()` (used internally)
- **Convenience function**: `setup_tracing()` (called by business layer)

Without explicit initialization, OpenTelemetry uses NoOp provider (zero overhead).

---

## Quick Start: Export to Jaeger

### Step 1: Install Dependencies

```bash
# Install observability extra (SDK + OTLP exporter + LangChain instrumentation)
uv sync --extra observability
```

### Step 2: Start Jaeger (Docker)

```bash
docker run --rm -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

Access Jaeger UI: `http://localhost:16686`

### Step 3: Initialize Tracing

```python
from myrm_agent_harness.infra.tracing import setup_tracing

# Add OTLP exporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry import trace

# Create provider
provider = TracerProvider()

# Add OTLP exporter (Jaeger supports OTLP protocol)
otlp_exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",  # Jaeger OTLP port
    insecure=True,  # For local development
)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

# Set global provider
trace.set_tracer_provider(provider)
```

### Step 4: Verify

Run your agent, then open `http://localhost:16686` and search for traces.

---

## Alternative: Export to Zipkin

### Step 1: Install Zipkin Exporter

```bash
uv add opentelemetry-exporter-zipkin
```

### Step 2: Start Zipkin

```bash
docker run --rm -d --name zipkin \
  -p 9411:9411 \
  openzipkin/zipkin
```

Access Zipkin UI: `http://localhost:9411`

### Step 3: Configure Exporter

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.zipkin.json import ZipkinExporter
from opentelemetry import trace

provider = TracerProvider()
zipkin_exporter = ZipkinExporter(
    endpoint="http://localhost:9411/api/v2/spans",
)
provider.add_span_processor(BatchSpanProcessor(zipkin_exporter))
trace.set_tracer_provider(provider)
```

---

## Production Configuration

### 1. Sampling Strategy

**Problem**: In high-traffic production, 100% sampling generates massive data volume.

**Solution**: Configure sampling ratio.

```python
from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    TraceIdRatioBased,
)

# Sample 10% of traces
sampler = ParentBased(
    root=TraceIdRatioBased(0.1)  # 10% sampling
)

provider = TracerProvider(sampler=sampler)
```

**Sampling Strategy Table**:


| Environment               | Sample Rate | Rationale               |
| ------------------------- | ----------- | ----------------------- |
| Development               | 100% (1.0)  | Debug all requests      |
| Staging                   | 50% (0.5)   | Balance coverage & cost |
| Production (low traffic)  | 10% (0.1)   | Reduce storage 90%      |
| Production (high traffic) | 1% (0.01)   | Keep only 1% traces     |


### 2. OTLP Endpoint Configuration

**Best Practice**: Use environment variables for flexibility.

```python
import os
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
otlp_exporter = OTLPSpanExporter(
    endpoint=endpoint,
    insecure=endpoint.startswith("http://"),  # Auto-detect
)
```

**Environment Variables**:

```bash
# .env.production
OTEL_EXPORTER_OTLP_ENDPOINT=https://jaeger.example.com:4317
OTEL_SAMPLE_RATE=0.01  # 1% sampling

# .env.development
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SAMPLE_RATE=1.0  # 100% sampling
```

### 3. Trace Context Propagation

**Use Case**: Cross-service tracing (control plane → sandbox → agent)

```python
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# Sender (control plane)
propagator = TraceContextTextMapPropagator()
carrier = {}
propagator.inject(carrier)  # Inject 'traceparent' header

# Send to sandbox with header
response = requests.post(
    "http://sandbox:8080/execute",
    headers=carrier,  # e.g., {"traceparent": "00-..."}
)

# Receiver (sandbox)
context = propagator.extract(carrier=request.headers)
with tracer.start_as_current_span("execute_in_sandbox", context=context):
    # This span will be part of the same trace
    pass
```

### 4. Performance Optimization

**Best Practices**:

1. **Batch Processing**: Use `BatchSpanProcessor` (default) instead of `SimpleSpanProcessor`
  - Buffer: 512 spans per batch (default)
  - Timeout: 5 seconds (default)
2. **Async Export**: Export happens in background thread (zero blocking)
3. **Bounded Queue**: Set `max_queue_size` to prevent memory leak
  ```python
   processor = BatchSpanProcessor(
       exporter,
       max_queue_size=2048,
       max_export_batch_size=512,
       schedule_delay_millis=5000,
   )
  ```

---

## Integration with Prometheus Metrics

**Pattern**: Associate trace_id with metrics for correlation.

```python
from opentelemetry import trace
from prometheus_client import Counter

request_counter = Counter("http_requests_total", "Total requests", ["trace_id"])

# In request handler
span = trace.get_current_span()
trace_id = format(span.get_span_context().trace_id, "032x")

# Record metric with trace_id label
request_counter.labels(trace_id=trace_id).inc()
```

**Use Case**: In Grafana, click a metric spike → see trace_id → jump to Jaeger for full trace.

---

## Troubleshooting

### Issue 1: No Traces in Jaeger

**Check**:

1. Jaeger is running: `curl http://localhost:16686/api/services`
2. OTLP endpoint is correct: `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`
3. Exporter is initialized: Check logs for "Tracing initialized"
4. Sampling ratio is not 0: Check `sampler` configuration

### Issue 2: Traces Missing Spans

**Cause**: Framework code not instrumented with `trace_async()` or `trace_context()`.

**Solution**: Ensure all key operations use tracing decorators.

```python
from myrm_agent_harness.infra.tracing import trace_async

@trace_async()
async def my_function():
    # This function will be traced
    pass
```

### Issue 3: High Storage Cost

**Solution**: Reduce sampling rate.

```python
# Production: sample only 1%
sampler = ParentBased(root=TraceIdRatioBased(0.01))
```

---

## Reference

**Official Documentation**:

- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Jaeger](https://www.jaegertracing.io/docs/latest/)
- [Zipkin](https://zipkin.io/pages/quickstart.html)

**Framework Code**:

- `myrm_agent_harness/infra/tracing/tracer.py` - Tracer setup
- `myrm_agent_harness/infra/tracing/metrics/exporter.py` - Metrics export

**Environment Variables** (Standard):

- `OTEL_EXPORTER_OTLP_ENDPOINT` - OTLP endpoint URL
- `OTEL_SERVICE_NAME` - Service name for traces
- `OTEL_SAMPLE_RATE` - Sampling ratio (0.0-1.0)

