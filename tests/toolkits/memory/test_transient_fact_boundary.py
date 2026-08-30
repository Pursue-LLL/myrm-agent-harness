"""Unit tests for transient business fact memory boundary heuristics."""

import pytest
from myrm_agent_harness.toolkits.memory.agent_surface.transient_fact_boundary import (
    filter_transient_business_memories,
    get_transient_fact_rejection_count,
    looks_like_transient_business_fact,
    record_transient_fact_rejection,
    reset_transient_fact_rejection_count,
    transient_fact_save_rejection_message,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    ProceduralMemory,
    ProfileEntry,
    SemanticMemory,
)


class TestTransientFactBoundary:
    def setup_method(self) -> None:
        reset_transient_fact_rejection_count()

    def test_logistics_and_order_transient_facts_detected(self) -> None:
        transient_samples = [
            "Your order #123456 is out for delivery with courier",
            "Package SF998877 is in transit at sorting hub",
            "Tracking number US123456789HK is dispatched and awaiting pickup",
            "顺丰快递 SF10086 正在派送中",
            "订单 #20260830-01 已出库，正在分拨中心分拣中",
            "包裹 77332211 已到达菜鸟驿站自提柜",
            "您的外卖订单配送中，骑手已揽收",
        ]
        for sample in transient_samples:
            assert looks_like_transient_business_fact(sample), f"Should detect: {sample}"

    def test_financial_balance_transient_facts_detected(self) -> None:
        transient_samples = [
            "Current available balance is $150.00",
            "Wallet balance remaining: ¥2450",
            "Live credit limit is £500",
            "当前账户可用余额为 ¥12,450.00",
            "招行信用卡实时额度剩余 5000 元",
            "钱包可用金为 88.50",
        ]
        for sample in transient_samples:
            assert looks_like_transient_business_fact(sample), f"Should detect: {sample}"

    def test_auth_and_otp_transient_facts_detected(self) -> None:
        transient_samples = [
            "Your verification code is 839201",
            "SMS OTP: 492810",
            "Login security code is A9B8C7",
            "您的短信验证码为 952701",
            "动态授权码是 682910",
            "一次性登录密码: 382910",
        ]
        for sample in transient_samples:
            assert looks_like_transient_business_fact(sample), f"Should detect: {sample}"

    def test_ephemeral_links_and_queue_detected(self) -> None:
        transient_samples = [
            "Presigned URL expires in 15 mins: https://s3.aws.com/temp",
            "Temporary download link valid for 2 hours",
            "Queue position is 42, estimated wait time 10 minutes",
            "临时下载地址有效期还剩 10 分钟",
            "签名 url 有效时间为 300 秒",
            "当前排队进度当前第 5 位",
        ]
        for sample in transient_samples:
            assert looks_like_transient_business_fact(sample), f"Should detect: {sample}"

    def test_durable_preferences_and_profiles_not_blocked(self) -> None:
        durable_samples = [
            "User prefers SF Express for fast courier delivery",
            "User favorite shopping platform is Taobao",
            "User defaults to paying with China Merchants Bank Credit Card",
            "User VIP membership number is VIP-88888888",
            "User home shipping address is Room 501, Building 2, Beijing",
            "用户偏好顺丰速运发货",
            "用户常用支付方式是微信支付",
            "用户的会员卡号是 VIP999",
            "用户收货地址为北京市朝阳区科技园",
            "Prefers Python over TypeScript for backend development",
        ]
        for sample in durable_samples:
            assert not looks_like_transient_business_fact(sample), f"Should not block: {sample}"

    def test_filter_transient_business_memories(self) -> None:
        memories = [
            SemanticMemory(content="Prefers dark theme in all IDEs"),
            SemanticMemory(content="Order #9981 is out for delivery today"),
            EpisodicMemory(content="顺丰快递 SF12345 正在派送中"),
            ProfileEntry(key="preferred_courier", value="SF Express"),
            ProceduralMemory(trigger="shopping", action="Ask for invoice"),
        ]

        kept, dropped = filter_transient_business_memories(memories)
        assert dropped == 2
        assert len(kept) == 3
        contents = [getattr(m, "content", getattr(m, "key", "")) for m in kept]
        assert "Prefers dark theme in all IDEs" in contents
        assert "preferred_courier" in contents
        assert getattr(kept[2], "action", "") == "Ask for invoice"

    def test_rejection_message_and_counter(self) -> None:
        assert get_transient_fact_rejection_count() == 0
        cnt = record_transient_fact_rejection()
        assert cnt == 1
        assert get_transient_fact_rejection_count() == 1

        msg = transient_fact_save_rejection_message()
        assert "Rejected: content represents a real-time transient business state" in msg
        assert "MemorySession" in msg
