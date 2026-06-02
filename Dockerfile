# Myrm Agent Image - Agent-in-Sandbox Runtime
#
# Multi-stage build that creates a self-contained agent image:
# Stage 1: Build myrm-agent-harness + myrm-control-plane sandbox_runtime
# Stage 2: Combine with skill-sandbox base image
#
# The agent image contains everything needed to run an agent inside a sandbox:
# - myrm-agent-harness (agent framework, tools, browser automation)
# - sandbox_runtime (WebSocket client, agent runner, proxied LLM)
# - Patchright browser (anti-detection Chromium)
# - Python data science stack (from skill-sandbox base)
#
# Usage:
#   docker build -t myrm-agent:latest -f Dockerfile --build-context control-plane=../myrm-control-plane .
#   docker run -e CONTROL_PLANE_URL=ws://host:8001/ws -e SANDBOX_ID=abc123 myrm-agent:latest

# ============================================================================
# Stage 1: Build - Install harness + sandbox_runtime packages
# ============================================================================
FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system ".[browser,retrieval,file-parsers,monitoring]"

# Install sandbox_runtime from control-plane
COPY --from=control-plane pyproject.toml /cp/pyproject.toml
COPY --from=control-plane src/ /cp/src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system /cp

# Install the harness itself
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system .

# ============================================================================
# Stage 2: Runtime - Based on skill-sandbox for rich tooling
# ============================================================================
FROM open-perplexity/skill-sandbox:latest AS runtime

USER root

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

ENV PYTHONPATH=/usr/local/lib/python3.14/site-packages:$PYTHONPATH \
    PATCHRIGHT_BROWSERS_PATH=/home/sandbox/.cache/ms-playwright

# Install Patchright browser (anti-detection Chromium)
RUN python -m patchright install chromium --with-deps 2>/dev/null || true

# Verify critical packages
RUN python -c "\
from myrm_agent_harness.agent import create_skill_agent; \
from myrm_control_plane.sandbox_runtime.agent_runner import AgentRunner; \
print('✅ Agent packages verified')"

USER sandbox

WORKDIR /workspace

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import myrm_agent_harness; print('ok')" || exit 1

ENTRYPOINT ["python", "-m", "myrm_control_plane.sandbox_runtime.agent_runner"]
