"""Complete coverage tests for throttle strategies"""

import asyncio
from typing import cast

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import RateLimiterConfig, ThrottleMode
from myrm_agent_harness.toolkits.browser.pool.throttle import (
    DomainThrottle,
    NoThrottle,
    create_throttle_strategy,
)


class TestNoThrottle:
    """Tests for NoThrottle strategy"""

    @pytest.mark.asyncio
    async def test_before_navigate_does_nothing(self):
        """Test NoThrottle.before_navigate does nothing"""
        throttle = NoThrottle()
        await throttle.before_navigate("http://example.com")

    def test_record_response_does_nothing(self):
        """Test NoThrottle.record_response does nothing"""
        throttle = NoThrottle()
        throttle.record_response("http://example.com", True)
        throttle.record_response("http://example.com", False)


class TestDomainThrottleTokenBucket:
    """Tests for DomainThrottle token bucket logic"""

    @pytest.mark.asyncio
    async def test_token_bucket_waits_when_exhausted(self):
        """测试：token bucket 耗尽时等待补充"""
        config = RateLimiterConfig(
            mode=ThrottleMode.DOMAIN,
            domain_qps=10.0,  # 10 QPS = 0.1s per token
            domain_burst=2,
        )
        throttle = DomainThrottle(config)

        # 快速消耗所有 tokens（2次请求）
        await throttle.before_navigate("http://example.com")
        await throttle.before_navigate("http://example.com")

        # 第3次请求应该等待（token bucket empty）
        start = asyncio.get_event_loop().time()
        await throttle.before_navigate("http://example.com")
        elapsed = asyncio.get_event_loop().time() - start

        # 验证等待了至少 0.08s（0.1s per token - tolerance）
        assert elapsed >= 0.08

    @pytest.mark.asyncio
    async def test_token_bucket_refills_over_time(self):
        """测试：token bucket 随时间自动补充"""
        config = RateLimiterConfig(
            mode=ThrottleMode.DOMAIN,
            domain_qps=10.0,  # 10 QPS = 0.1s per token
            domain_burst=2,
        )
        throttle = DomainThrottle(config)

        # 消耗1个token
        await throttle.before_navigate("http://example.com")

        # 等待0.15s（应该补充1.5个token）
        await asyncio.sleep(0.15)

        # 再次请求2次（应该成功，不等待）
        start = asyncio.get_event_loop().time()
        await throttle.before_navigate("http://example.com")
        await throttle.before_navigate("http://example.com")
        elapsed = asyncio.get_event_loop().time() - start

        # 验证几乎无等待（< 0.05s）
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_token_bucket_different_domains_independent(self):
        """测试：不同域名的 token bucket 独立"""
        config = RateLimiterConfig(
            mode=ThrottleMode.DOMAIN,
            domain_qps=10.0,
            domain_burst=1,
        )
        throttle = DomainThrottle(config)

        # domain1 消耗所有tokens
        await throttle.before_navigate("http://domain1.com")

        # domain2 应该有满的token bucket（不等待）
        start = asyncio.get_event_loop().time()
        await throttle.before_navigate("http://domain2.com")
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.01


class TestCreateThrottleStrategy:
    """Tests for create_throttle_strategy factory"""

    def test_create_none_throttle(self):
        """Test creates NoThrottle for NONE mode"""
        config = RateLimiterConfig(mode=ThrottleMode.NONE)
        strategy = create_throttle_strategy(config)
        assert isinstance(strategy, NoThrottle)

    def test_create_domain_throttle(self):
        """Test creates DomainThrottle for DOMAIN mode"""
        config = RateLimiterConfig(mode=ThrottleMode.DOMAIN)
        strategy = create_throttle_strategy(config)
        assert isinstance(strategy, DomainThrottle)

    def test_create_unknown_mode_raises_error(self):
        """测试：未知模式抛出异常"""
        config = RateLimiterConfig(mode=cast(ThrottleMode, "unknown"))

        with pytest.raises(ValueError, match="Unknown throttle mode"):
            create_throttle_strategy(config)
