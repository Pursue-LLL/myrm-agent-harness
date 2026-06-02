from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.event_log.types import AntiPattern, FileHotspot, TraceRunDigest
from myrm_agent_harness.agent.middlewares.task_adaptive_middleware import TaskAdaptiveMiddleware


def test_task_adaptive_middleware_injects_on_first_human_message():
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Refactor Database",
        hotspots=[FileHotspot("main.py", 1, 1, 0.0)],
        anti_patterns=[
            AntiPattern(
                error_signature="Crash", failed_tool="bad_tool", failed_args={}, user_correction="fixed", timestamp=0.0
            )
        ],
        success_rate=1.0,
        duration_ms=100.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Hello")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    assert isinstance(result[1], HumanMessage)
    assert "<task_adaptive_context>" in result[1].content
    assert "main.py" in result[1].content
    assert "fixed" in result[1].content
    assert middleware._injected is True


def test_task_adaptive_middleware_skips_on_second_human_message():
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Refactor",
        hotspots=[FileHotspot("main.py", 1, 1, 0.0)],
        anti_patterns=[],
        success_rate=1.0,
        duration_ms=100.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [
        SystemMessage(content="You are an AI"),
        HumanMessage(content="Hello"),
        AIMessage(content="Hi"),
        HumanMessage(content="Do something"),
    ]

    result = middleware._process_messages(messages)

    assert len(result) == 4
    assert "<task_adaptive_context>" not in result[1].content
    assert "<task_adaptive_context>" not in result[3].content
    assert middleware._injected is False


def test_task_adaptive_middleware_with_only_hotspots():
    """Test that middleware correctly injects when only hotspots are provided."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Refactor",
        hotspots=[
            FileHotspot("database.py", 5, 3, 0.0),
            FileHotspot("models.py", 10, 2, 0.0),
        ],
        anti_patterns=[],
        success_rate=1.0,
        duration_ms=100.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Hello")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    assert isinstance(result[1], HumanMessage)
    assert "<task_adaptive_context>" in result[1].content
    assert "database.py" in result[1].content
    assert "models.py" in result[1].content
    assert "Reads: 5" in result[1].content
    assert "Writes: 3" in result[1].content
    assert middleware._injected is True


def test_task_adaptive_middleware_with_only_anti_patterns():
    """Test that middleware correctly injects when only anti-patterns are provided."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Fix Bug",
        hotspots=[],
        anti_patterns=[
            AntiPattern(
                error_signature="TypeError: NoneType",
                failed_tool="file_write",
                failed_args={},
                user_correction="Always validate input before writing",
                timestamp=0.0,
            )
        ],
        success_rate=0.5,
        duration_ms=200.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Debug this")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    assert isinstance(result[1], HumanMessage)
    assert "<task_adaptive_context>" in result[1].content
    assert "TypeError: NoneType" in result[1].content
    assert "Always validate input before writing" in result[1].content
    assert middleware._injected is True


def test_task_adaptive_middleware_with_empty_digest():
    """Test that middleware skips injection when digest has no evidence."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Simple Task",
        hotspots=[],
        anti_patterns=[],
        success_rate=1.0,
        duration_ms=50.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Hello")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    assert isinstance(result[1], HumanMessage)
    assert "<task_adaptive_context>" not in result[1].content
    assert middleware._injected is False


def test_task_adaptive_middleware_with_no_digest():
    """Test that middleware works correctly when no digest is provided."""
    middleware = TaskAdaptiveMiddleware(trace_digest=None)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Hello")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    assert result == messages
    assert middleware._injected is False


def test_task_adaptive_middleware_with_multimodal_content():
    """Test that middleware correctly handles multi-modal content (list of dicts)."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Image Analysis",
        hotspots=[FileHotspot("image_processor.py", 3, 1, 0.0)],
        anti_patterns=[],
        success_rate=1.0,
        duration_ms=100.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [
        SystemMessage(content="You are an AI"),
        HumanMessage(
            content=[
                {"type": "text", "text": "Analyze this image"},
                {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}},
            ]
        ),
    ]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    assert isinstance(result[1], HumanMessage)
    assert isinstance(result[1].content, list)
    assert len(result[1].content) == 3
    assert result[1].content[0]["type"] == "text"
    assert result[1].content[1]["type"] == "image_url"
    assert result[1].content[2]["type"] == "text"
    assert "<task_adaptive_context>" in result[1].content[2]["text"]
    assert "image_processor.py" in result[1].content[2]["text"]
    assert middleware._injected is True


def test_task_adaptive_middleware_with_multiple_hotspots_truncation():
    """Test that middleware truncates to top 5 hotspots."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Refactor",
        hotspots=[
            FileHotspot(f"file{i}.py", i, i, 0.0) for i in range(1, 11)
        ],  # 10 hotspots
        anti_patterns=[],
        success_rate=1.0,
        duration_ms=100.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Hello")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    content = result[1].content
    assert "<task_adaptive_context>" in content
    assert "file1.py" in content
    assert "file5.py" in content
    assert "file6.py" not in content
    assert middleware._injected is True


def test_task_adaptive_middleware_with_multiple_anti_patterns_truncation():
    """Test that middleware truncates to top 3 anti-patterns."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Fix Bugs",
        hotspots=[],
        anti_patterns=[
            AntiPattern(
                error_signature=f"Error {i}",
                failed_tool=f"tool{i}",
                failed_args={},
                user_correction=f"Fix {i}",
                timestamp=0.0,
            )
            for i in range(1, 6)
        ],  # 5 anti-patterns
        success_rate=0.5,
        duration_ms=200.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    messages = [SystemMessage(content="You are an AI"), HumanMessage(content="Debug")]

    result = middleware._process_messages(messages)

    assert len(result) == 2
    content = result[1].content
    assert "<task_adaptive_context>" in content
    assert "Error 1" in content
    assert "Error 3" in content
    assert "Error 4" not in content
    assert middleware._injected is True


def test_task_adaptive_middleware_with_no_human_message():
    """Test that middleware appends a new HumanMessage when none exists (fallback)."""
    digest = TraceRunDigest(
        session_id="test",
        task_intent="Fallback Test",
        hotspots=[FileHotspot(file_path="config.py", read_count=1, write_count=0, last_accessed=1.0)],
        anti_patterns=[],
        success_rate=1.0,
        duration_ms=50.0,
    )
    middleware = TaskAdaptiveMiddleware(trace_digest=digest)

    # Only SystemMessage, no HumanMessage
    messages = [SystemMessage(content="You are an AI")]

    result = middleware._process_messages(messages)

    # Should append a new HumanMessage with the task-adaptive context
    assert len(result) == 2
    assert isinstance(result[0], SystemMessage)
    assert isinstance(result[1], HumanMessage)
    assert "<task_adaptive_context>" in result[1].content
    assert "config.py" in result[1].content
    assert middleware._injected is True
