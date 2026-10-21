"""inject_ephemeral_quote 单元测试 — 划词引用内联注入

覆盖场景：
- 正常注入：引用文本内联到 HumanMessage.content
- 空消息列表
- 最后一条不是 HumanMessage
- 无 quote_attachment
- quote_attachment 类型不匹配
- 多模态 content（list 类型）跳过
- 注入后 additional_kwargs 保留
- 历史消息零修改（Prompt Cache 安全）
"""

import copy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.streaming.message_builder import inject_ephemeral_quote
from myrm_agent_harness.agent.types import QuoteAttachment


class TestInjectEphemeralQuote:
    """inject_ephemeral_quote 的单元测试"""

    def _make_messages(
        self, user_text: str = "请解释这个概念", quote: QuoteAttachment | None = None, history_count: int = 2
    ) -> list[HumanMessage | AIMessage | SystemMessage]:
        msgs: list[HumanMessage | AIMessage | SystemMessage] = [
            SystemMessage(content="You are a helpful assistant."),
        ]
        for i in range(history_count):
            msgs.append(HumanMessage(content=f"历史问题 {i}"))
            msgs.append(AIMessage(content=f"历史回答 {i}"))

        kwargs: dict[str, object] = {}
        if quote is not None:
            kwargs["quote_attachment"] = quote
        msgs.append(HumanMessage(content=user_text, additional_kwargs=kwargs))
        return msgs

    def test_normal_injection(self) -> None:
        """引用文本以 <quoted_context> 标签内联到 HumanMessage.content"""
        quote = QuoteAttachment(source_message_id="msg-123", quoted_text="被引用的原文内容")
        msgs = self._make_messages(quote=quote)
        original_last_content = msgs[-1].content

        inject_ephemeral_quote(msgs)

        last = msgs[-1]
        assert isinstance(last, HumanMessage)
        assert '<quoted_context source="msg-123">' in last.content
        assert "被引用的原文内容" in last.content
        assert "</quoted_context>" in last.content
        assert str(original_last_content) in last.content

    def test_quoted_context_precedes_original_content(self) -> None:
        """引用文本必须在原始内容之前"""
        quote = QuoteAttachment(source_message_id="msg-abc", quoted_text="引用内容")
        msgs = self._make_messages(user_text="用户提问", quote=quote)

        inject_ephemeral_quote(msgs)

        content = msgs[-1].content
        assert isinstance(content, str)
        quote_pos = content.index("<quoted_context")
        original_pos = content.index("用户提问")
        assert quote_pos < original_pos

    def test_empty_messages(self) -> None:
        """空消息列表不崩溃"""
        msgs: list[HumanMessage] = []
        inject_ephemeral_quote(msgs)
        assert msgs == []

    def test_last_not_human_message(self) -> None:
        """最后一条非 HumanMessage 时不注入"""
        msgs = self._make_messages()
        msgs.append(AIMessage(content="AI 回复"))

        original_len = len(msgs)
        inject_ephemeral_quote(msgs)
        assert len(msgs) == original_len

    def test_no_quote_attachment(self) -> None:
        """无 quote_attachment 时不注入"""
        msgs = self._make_messages(quote=None)
        original_content = msgs[-1].content

        inject_ephemeral_quote(msgs)
        assert msgs[-1].content == original_content

    def test_wrong_type_quote_attachment(self) -> None:
        """quote_attachment 类型不是 QuoteAttachment 时不注入"""
        msgs = self._make_messages()
        msgs[-1].additional_kwargs["quote_attachment"] = "not a QuoteAttachment"
        original_content = msgs[-1].content

        inject_ephemeral_quote(msgs)
        assert msgs[-1].content == original_content

    def test_multimodal_content_skipped(self) -> None:
        """content 为 list（多模态）时不注入"""
        quote = QuoteAttachment(source_message_id="msg-multi", quoted_text="引用")
        multimodal_content = [{"type": "text", "text": "描述"}, {"type": "image_url", "image_url": {"url": "data:..."}}]
        msgs: list[HumanMessage | SystemMessage] = [
            SystemMessage(content="system"),
            HumanMessage(content=multimodal_content, additional_kwargs={"quote_attachment": quote}),
        ]

        inject_ephemeral_quote(msgs)
        assert msgs[-1].content == multimodal_content

    def test_additional_kwargs_preserved(self) -> None:
        """注入后 additional_kwargs 中其他字段保留"""
        quote = QuoteAttachment(source_message_id="msg-456", quoted_text="引用")
        msgs = self._make_messages(quote=quote)
        msgs[-1].additional_kwargs["custom_field"] = "custom_value"

        inject_ephemeral_quote(msgs)

        assert msgs[-1].additional_kwargs.get("custom_field") == "custom_value"
        assert msgs[-1].additional_kwargs.get("quote_attachment") is quote

    def test_history_messages_untouched(self) -> None:
        """历史消息零修改（Prompt Cache 安全验证）"""
        quote = QuoteAttachment(source_message_id="msg-789", quoted_text="引用")
        msgs = self._make_messages(quote=quote, history_count=3)

        history_snapshot = [copy.deepcopy(m) for m in msgs[:-1]]

        inject_ephemeral_quote(msgs)

        for original, current in zip(history_snapshot, msgs[:-1], strict=False):
            assert original.content == current.content
            assert original.additional_kwargs == current.additional_kwargs

    def test_source_id_in_xml_attribute(self) -> None:
        """source_message_id 作为 XML 属性正确嵌入"""
        quote = QuoteAttachment(source_message_id="db-id-xyz-789", quoted_text="text")
        msgs = self._make_messages(quote=quote)

        inject_ephemeral_quote(msgs)

        content = msgs[-1].content
        assert isinstance(content, str)
        assert 'source="db-id-xyz-789"' in content

    @pytest.mark.parametrize(
        "quoted_text",
        [
            "短",
            "a" * 2000,
            "包含<特殊>XML&字符的\"文本'",
            "多行\n引用\n文本",
        ],
        ids=["short", "long_2000", "xml_special_chars", "multiline"],
    )
    def test_various_quote_texts(self, quoted_text: str) -> None:
        """各种引用文本内容均能正确注入"""
        quote = QuoteAttachment(source_message_id="msg-var", quoted_text=quoted_text)
        msgs = self._make_messages(quote=quote)

        inject_ephemeral_quote(msgs)

        content = msgs[-1].content
        assert isinstance(content, str)
        assert quoted_text in content

    def test_consecutive_injections_independent(self) -> None:
        """连续两次注入互不影响"""
        q1 = QuoteAttachment(source_message_id="msg-1", quoted_text="第一次引用")
        msgs1 = self._make_messages(user_text="问题1", quote=q1)
        inject_ephemeral_quote(msgs1)

        q2 = QuoteAttachment(source_message_id="msg-2", quoted_text="第二次引用")
        msgs2 = self._make_messages(user_text="问题2", quote=q2)
        inject_ephemeral_quote(msgs2)

        content1 = msgs1[-1].content
        content2 = msgs2[-1].content
        assert isinstance(content1, str)
        assert isinstance(content2, str)
        assert "第一次引用" in content1
        assert "第二次引用" in content2
        assert "第二次引用" not in content1
        assert "第一次引用" not in content2

    def test_empty_quoted_text_still_injects(self) -> None:
        """空引用文本仍然注入（QuoteAttachment 允许空字符串）"""
        quote = QuoteAttachment(source_message_id="msg-empty", quoted_text="")
        msgs = self._make_messages(quote=quote)

        inject_ephemeral_quote(msgs)

        content = msgs[-1].content
        assert isinstance(content, str)
        assert "<quoted_context" in content

    def test_single_message_no_history(self) -> None:
        """无历史消息时正常注入"""
        quote = QuoteAttachment(source_message_id="msg-solo", quoted_text="solo引用")
        msgs = [HumanMessage(content="单独问题", additional_kwargs={"quote_attachment": quote})]

        inject_ephemeral_quote(msgs)

        content = msgs[-1].content
        assert isinstance(content, str)
        assert "solo引用" in content
        assert "单独问题" in content
