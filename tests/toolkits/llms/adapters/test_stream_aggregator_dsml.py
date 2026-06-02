from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from myrm_agent_harness.toolkits.llms.adapters.stream_aggregator import (
    StreamAggregator,
    XmlStreamBuffer,
    finalize_stream,
)


def test_finalize_stream_dsml_clean():
    agg = StreamAggregator(AIMessageChunk)

    # Simulate stream with DSML tags in content
    msg1 = AIMessageChunk(content="Thinking... \n<｜DSML｜tool_calls>\n")
    msg2 = AIMessageChunk(content="<｜DSML｜invoke name=\"search_web\">\n<｜DSML｜parameter name=\"query\" string=\"true\">test</｜DSML｜parameter>\n")
    msg3 = AIMessageChunk(content="</｜DSML｜invoke>\n</｜DSML｜tool_calls>")

    agg.on_generation_chunk(ChatGenerationChunk(message=msg1), AIMessageChunk)
    agg.on_generation_chunk(ChatGenerationChunk(message=msg2), AIMessageChunk)
    agg.on_generation_chunk(ChatGenerationChunk(message=msg3), AIMessageChunk)

    res = finalize_stream(
        agg=agg,
        tool_schemas=None,
        model_name="deepseek-v4",
        is_async=False,
        record_usage_fn=lambda *args, **kwargs: None,
        available_tools=["search_web"]
    )

    response_msg = res.aggregated_response["choices"][0]["message"]

    # Tool call should be parsed
    assert "tool_calls" in response_msg
    assert len(response_msg["tool_calls"]) == 1
    assert response_msg["tool_calls"][0]["function"]["name"] == "search_web"

    # Text should be cleaned of DSML tags
    assert "<｜DSML｜tool_calls>" not in response_msg["content"]
    assert "Thinking..." in response_msg["content"]

def test_finalize_stream_dsml_clean_reasoning():
    agg = StreamAggregator(AIMessageChunk)

    # Simulate stream with DSML tags in reasoning
    msg1 = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "Deep thought... \n<｜DSML｜tool_calls>\n"})
    msg2 = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "<｜DSML｜invoke name=\"search_web\">\n<｜DSML｜parameter name=\"query\" string=\"true\">test</｜DSML｜parameter>\n</｜DSML｜invoke>\n</｜DSML｜tool_calls>"})

    agg.on_generation_chunk(ChatGenerationChunk(message=msg1), AIMessageChunk)
    agg.on_generation_chunk(ChatGenerationChunk(message=msg2), AIMessageChunk)

    res = finalize_stream(
        agg=agg,
        tool_schemas=None,
        model_name="deepseek-v4",
        is_async=False,
        record_usage_fn=lambda *args, **kwargs: None,
        available_tools=["search_web"]
    )

    response_msg = res.aggregated_response["choices"][0]["message"]

    # Tool call should be parsed
    assert "tool_calls" in response_msg
    assert len(response_msg["tool_calls"]) == 1
    assert response_msg["tool_calls"][0]["function"]["name"] == "search_web"

    # Reasoning text should be cleaned of DSML tags
    assert "<｜DSML｜tool_calls>" not in response_msg["reasoning_content"]
    assert "Deep thought..." in response_msg["reasoning_content"]

def test_aggregator_ingest_and_dict():
    agg = StreamAggregator(AIMessageChunk)
    # mock a dict chunk
    chunk = {
        "model": "test_model",
        "usage": {"total_tokens": 10},
        "choices": [{"finish_reason": "stop", "delta": {"tool_calls": [{"function": {"name": "t1", "arguments": "{}"}}]}}]
    }
    res = agg.ingest_raw_chunk(chunk)
    assert res == chunk

    agg.aggregate_tool_calls_from_dict(chunk)
    assert agg.last_model == "test_model"
    assert agg.finish_reason == "stop"
    assert agg.last_usage == {"total_tokens": 10}
    assert len(agg.tool_calls) == 1

def test_xml_stream_buffer():
    buf = XmlStreamBuffer()

    # Not matching
    assert buf.process("hello ") == "hello "

    # Partial match DSML
    assert buf.process("<｜D") == ""
    assert buf.process("SML｜") == ""
    assert buf.process("tool_calls>") == ""
    assert buf.is_swallowing

    # Inside swallowing
    assert buf.process("some tool json") == ""

    # End tag DSML
    assert buf.process("</｜DSML｜tool_calls>") == ""
    assert not buf.is_swallowing

    # Partial match tool_call
    assert buf.process("<tool_") == ""
    assert buf.process("call>") == ""
    assert buf.is_swallowing
    assert buf.process("</tool_call>") == ""
    assert not buf.is_swallowing

    # Partial match invoke
    assert buf.process("<invok") == ""
    assert buf.process("e name='foo'>") == ""
    assert buf.is_swallowing
    assert buf.process("</invoke>") == ""
    assert not buf.is_swallowing

    # Mismatch fallback
    assert buf.process("<tab") == "<"
    assert buf.process("le>") == "table>"
    assert not buf.is_swallowing

    # Flush
    assert buf.process("<tool_") == ""
    assert buf.flush() == "<tool_"

    buf2 = XmlStreamBuffer()
    # Unclosed tag flush inside swallow
    buf2.process("<tool_call>")
    assert buf2.is_swallowing
    assert buf2.flush() == ""
