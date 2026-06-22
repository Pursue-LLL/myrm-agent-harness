"""[INPUT]
- performance.py::register_benchmark (POS: Register an async performance benchmark hook function.)
- protocols.py::HealthReport (POS: Component health status report.)

[OUTPUT]
- benchmark_llm_ttft: Measure LLM Time-To-First-Token and generation speed.
- benchmark_embedding_latency: Measure Embedding latency.
- benchmark_search_latency: Measure Search API latency.

[POS]
Provides performance benchmark probes for LLM, Embedding, and Search.
"""

import logging
import time

from myrm_agent_harness.observability.diagnostics.performance import register_benchmark
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

logger = logging.getLogger(__name__)


async def benchmark_llm_ttft() -> HealthReport:
    """Measure LLM Time-To-First-Token and generation speed."""
    try:
        from langchain_core.messages import HumanMessage

        from myrm_agent_harness.toolkits.llms.factory import get_default_llm

        llm = get_default_llm()
        if not llm:
            return HealthReport(
                component_name="LLM_Performance",
                status="warn",
                message="LLM provider not configured.",
                detail="Cannot run LLM benchmark because no default LLM is configured.",
            )

        start_time = time.perf_counter()
        first_token_time = None
        token_count = 0

        # We use a simple prompt to minimize input token processing time
        # and focus on network/provider TTFT.
        messages = [HumanMessage(content="Please reply with exactly one word: 'pong'")]

        async for _chunk in llm.astream(messages):
            if first_token_time is None:
                first_token_time = time.perf_counter()
            token_count += 1

        end_time = time.perf_counter()

        if first_token_time is None:
            raise ValueError("LLM returned no tokens.")

        ttft = first_token_time - start_time
        total_time = end_time - start_time

        # Calculate TPS (Tokens Per Second)
        # Avoid division by zero if total_time == ttft
        gen_time = end_time - first_token_time
        tps = token_count / gen_time if gen_time > 0 else 0.0

        status = "pass"
        if ttft > 3.0:
            status = "warn"
        if ttft > 8.0:
            status = "fail"

        return HealthReport(
            component_name="LLM_Performance",
            status=status,
            message=f"LLM TTFT: {ttft:.2f}s",
            detail=f"TTFT: {ttft:.2f}s, Tokens: {token_count}, TPS: {tps:.1f}",
            metrics={"ttft_s": ttft, "tps": tps, "total_time_s": total_time},
            fix_suggestion="Consider switching LLM providers if TTFT is consistently high."
            if status != "pass"
            else None,
        )
    except Exception as e:
        return HealthReport(
            component_name="LLM_Performance",
            status="fail",
            message="LLM benchmark failed.",
            detail=str(e),
        )


async def benchmark_embedding_latency() -> HealthReport:
    """Measure Embedding latency."""
    try:
        from myrm_agent_harness.toolkits.llms.factory import get_default_embeddings

        embeddings = get_default_embeddings()
        if not embeddings:
            return HealthReport(
                component_name="Embedding_Performance",
                status="warn",
                message="Embedding provider not configured.",
                detail="Cannot run Embedding benchmark because no default embeddings are configured.",
            )

        start_time = time.perf_counter()

        # Standard test chunk
        test_text = "This is a standard test sentence to measure embedding latency. " * 10

        await embeddings.aembed_query(test_text)

        end_time = time.perf_counter()
        latency = end_time - start_time

        status = "pass"
        if latency > 2.0:
            status = "warn"
        if latency > 5.0:
            status = "fail"

        return HealthReport(
            component_name="Embedding_Performance",
            status=status,
            message=f"Embedding Latency: {latency:.2f}s",
            detail=f"Latency for standard chunk: {latency:.2f}s",
            metrics={"latency_s": latency},
            fix_suggestion="Check embedding provider latency or switch to a faster model/API endpoint."
            if status != "pass"
            else None,
        )
    except Exception as e:
        return HealthReport(
            component_name="Embedding_Performance",
            status="fail",
            message="Embedding benchmark failed.",
            detail=str(e),
        )


async def benchmark_search_latency() -> HealthReport:
    """Measure Search API latency."""
    try:
        from myrm_agent_harness.toolkits.web_search.factory import get_search_provider

        search_provider = get_search_provider()
        if not search_provider:
            return HealthReport(
                component_name="Search_Performance",
                status="warn",
                message="Search provider not configured.",
                detail="Cannot run Search benchmark because no search provider is configured.",
            )

        start_time = time.perf_counter()

        # We search for a common term
        await search_provider.search("Artificial Intelligence", limit=1)

        end_time = time.perf_counter()
        latency = end_time - start_time

        status = "pass"
        if latency > 3.0:
            status = "warn"
        if latency > 8.0:
            status = "fail"

        return HealthReport(
            component_name="Search_Performance",
            status=status,
            message=f"Search Latency: {latency:.2f}s",
            detail=f"Latency for standard search query: {latency:.2f}s",
            metrics={"latency_s": latency},
            fix_suggestion="Check your network connection or search API provider status." if status != "pass" else None,
        )
    except Exception as e:
        return HealthReport(
            component_name="Search_Performance",
            status="fail",
            message="Search benchmark failed.",
            detail=str(e),
        )


register_benchmark(benchmark_llm_ttft)
register_benchmark(benchmark_embedding_latency)
register_benchmark(benchmark_search_latency)
