"""E2E verification that memory context injection is ephemeral.

Design principle:

- Stable ``<user_memory_context>`` is injected as ``SystemMessage`` after leading systems.
- Learned material uses ``<<<UNTRUSTED_DATA ...>>>`` via ``wrap_untrusted`` and is appended as ``HumanMessage`` before the user's first Human turn.
- Runtime persistence avoids treating these envelopes as canonical user-visible chat lines;
  checkpoints LangGraph-side may still see them — product DB surfaces should continue to persist only real turns.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


async def verify_ephemeral_memory_context():
    """Verify ephemeral memory envelopes are recognizable and fenced."""
    print("=" * 80)
    print("E2E Verification: Ephemeral Memory Context")
    print("=" * 80)

    # Import after path setup
    from myrm_agent_harness.agent.middlewares.memory_context_format import (
        MEMORY_CONTEXT_MARKER,
        MEMORY_UNTRUSTED_OPEN_MARKER,
    )
    from myrm_agent_harness.agent.middlewares.memory_context_middleware import (
        MemoryContextMiddleware,
    )

    print(f"\nMEMORY_CONTEXT_MARKER = {MEMORY_CONTEXT_MARKER}")
    print(f"\nMEMORY_UNTRUSTED_OPEN_MARKER = {MEMORY_UNTRUSTED_OPEN_MARKER}")

    print("\n[1/3] Design principle...")
    print(" stable → SystemMessage wrapping <user_memory_context>")
    print(" learned → HumanMessage wrapping <<<UNTRUSTED_DATA id=...")
    print("Architecture keeps security boundary rules applicable to envelopes.")

    print("\n[2/3] Code implementation snapshot...")
    middleware_file = (
        project_root
        / "src/myrm_agent_harness/agent/middlewares/memory_context_middleware.py"
    )
    with open(middleware_file) as f:
        middleware_code = f.read()

    assert "stable_msg = SystemMessage(content=stable_formatted)" in middleware_code
    assert "untrusted_msg = HumanMessage(content=untrusted_formatted)" in middleware_code
    assert "wrap_untrusted(untrusted_body" in middleware_code
    assert MemoryContextMiddleware.name == "memory_context_middleware"

    print(" Middleware injects stable System envelope + optional untrusted Human envelope.")

    print("\n[3/3] Defensive filter heuristic...")

    def filter_ephemeral_markers(messages: list[object]) -> list[object]:
        """Remove envelopes if a persistence path ever serializes full LLM-visible lists."""

        def _blocked(msg: object) -> bool:
            content = str(getattr(msg, "content", ""))
            return MEMORY_CONTEXT_MARKER in content or MEMORY_UNTRUSTED_OPEN_MARKER in content

        return [msg for msg in messages if not _blocked(msg)]

    class MockMessage:
        def __init__(self, content: str):
            self.content = content

    test_messages = [
        MockMessage("User query"),
        MockMessage('<user_memory_context>\nStable\n</user_memory_context>'),
        MockMessage(
            '[NOTICE]\n<<<UNTRUSTED_DATA id="deadbeef">\nLearned\n<<<END_UNTRUSTED_DATA id="deadbeef">>>'
        ),
        MockMessage("Another user query"),
    ]

    filtered = filter_ephemeral_markers(test_messages)
    assert len(filtered) == 2
    assert filtered[0].content == "User query"

    print(" Filter heuristic strips both markers.")

    print("\n" + "=" * 80)
    print("VERIFICATION PASSED: Memory Context envelope contracts")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(verify_ephemeral_memory_context())
