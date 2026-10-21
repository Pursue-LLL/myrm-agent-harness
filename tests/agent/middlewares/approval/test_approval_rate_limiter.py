"""Tests for approval_rate_limiter

测试审批速率限制器的功能：
1. 基本限制逻辑
2. 滑动窗口清理
3. 重置功能
"""

import time

import pytest

from myrm_agent_harness.agent.middlewares.approval import ApprovalRateLimiter, get_approval_rate_limiter


def test_rate_limiter_basic():
    """测试基本速率限制"""
    limiter = ApprovalRateLimiter(max_requests=3, window_seconds=60)

    # 前 3 次请求应该通过
    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user1") is True

    # 第 4 次请求应该被拒绝
    assert limiter.check_limit("user1") is False


def test_rate_limiter_different_users():
    """测试不同用户独立计数"""
    limiter = ApprovalRateLimiter(max_requests=2, window_seconds=60)

    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user2") is True
    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user2") is True

    # 两个用户都应该超限
    assert limiter.check_limit("user1") is False
    assert limiter.check_limit("user2") is False


def test_rate_limiter_sliding_window():
    """测试滑动窗口清理"""
    limiter = ApprovalRateLimiter(max_requests=2, window_seconds=1)

    # 填满限制
    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user1") is False

    # 等待窗口过期
    time.sleep(1.1)

    # 应该重新允许
    assert limiter.check_limit("user1") is True


def test_rate_limiter_get_remaining():
    """测试获取剩余请求数"""
    limiter = ApprovalRateLimiter(max_requests=5, window_seconds=60)

    assert limiter.get_remaining("user1") == 5

    limiter.check_limit("user1")
    assert limiter.get_remaining("user1") == 4

    limiter.check_limit("user1")
    limiter.check_limit("user1")
    assert limiter.get_remaining("user1") == 2


def test_rate_limiter_reset():
    """测试重置功能"""
    limiter = ApprovalRateLimiter(max_requests=1, window_seconds=60)

    # 填满限制
    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user1") is False

    # 重置单个用户
    limiter.reset("user1")
    assert limiter.check_limit("user1") is True


def test_rate_limiter_reset_all():
    """测试重置所有用户"""
    limiter = ApprovalRateLimiter(max_requests=1, window_seconds=60)

    # 多个用户填满限制
    limiter.check_limit("user1")
    limiter.check_limit("user2")

    assert limiter.check_limit("user1") is False
    assert limiter.check_limit("user2") is False

    # 重置所有
    limiter.reset()

    assert limiter.check_limit("user1") is True
    assert limiter.check_limit("user2") is True


def test_global_limiter_singleton():
    """测试全局单例"""
    limiter1 = get_approval_rate_limiter()
    limiter2 = get_approval_rate_limiter()

    assert limiter1 is limiter2

    # 重置状态，避免之前测试的影响
    limiter1.reset("singleton_test_user")

    # 全局单例应该记住状态
    limiter1.check_limit("singleton_test_user")
    assert limiter2.get_remaining("singleton_test_user") == 9  # 默认 10 次/分钟


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
