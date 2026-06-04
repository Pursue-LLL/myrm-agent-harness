import time

import pytest

from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyConfig, ProxyPoolExhaustedError, RoundRobinProxyPool


def test_proxy_config_to_url():
    config = ProxyConfig(server="http://proxy.example.com:8080")
    assert config.to_url() == "http://proxy.example.com:8080"

    config_auth = ProxyConfig(server="http://proxy.example.com:8080", username="user", password="pwd")
    assert config_auth.to_url() == "http://user:pwd@proxy.example.com:8080"

def test_proxy_config_to_playwright_dict():
    config = ProxyConfig(server="http://proxy.example.com:8080")
    assert config.to_playwright_dict() == {"server": "http://proxy.example.com:8080"}

    config_auth = ProxyConfig(server="http://proxy.example.com:8080", username="user", password="pwd")
    assert config_auth.to_playwright_dict() == {"server": "http://proxy.example.com:8080", "username": "user", "password": "pwd"}

def test_proxy_config_from_url():
    config = ProxyConfig.from_url("http://proxy.example.com:8080")
    assert config.server == "http://proxy.example.com:8080"
    assert config.username is None
    assert config.password is None

    config_auth = ProxyConfig.from_url("http://user:pwd@proxy.example.com:8080")
    assert config_auth.server == "http://proxy.example.com:8080"
    assert config_auth.username == "user"
    assert config_auth.password == "pwd"

def test_round_robin_proxy_pool_basic():
    proxies = [ProxyConfig(server=f"http://proxy{i}.com") for i in range(3)]
    pool = RoundRobinProxyPool(proxies)

    assert pool.get_next() == proxies[0]
    assert pool.get_next() == proxies[1]
    assert pool.get_next() == proxies[2]
    assert pool.get_next() == proxies[0]

def test_round_robin_proxy_pool_sticky_session():
    proxies = [ProxyConfig(server=f"http://proxy{i}.com") for i in range(3)]
    pool = RoundRobinProxyPool(proxies)

    p1 = pool.get_for_session("session1", ttl=3600)
    assert p1 == proxies[0]

    # Should get same proxy for same session
    assert pool.get_for_session("session1") == proxies[0]

    # New session gets next proxy
    p2 = pool.get_for_session("session2")
    assert p2 == proxies[1]

    assert pool.active_session_count == 2

    pool.release_session("session1")
    assert pool.active_session_count == 1

def test_round_robin_proxy_pool_quarantine_exponential_backoff(monkeypatch):
    proxies = [ProxyConfig(server=f"http://proxy{i}.com") for i in range(2)]
    pool = RoundRobinProxyPool(proxies)

    # Mock time.monotonic to control time
    current_time = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: current_time)

    p1 = pool.get_for_session("session1")
    assert p1 == proxies[0]

    # 1st failure: 60s quarantine
    pool.report_failure("session1", base_quarantine_seconds=60)
    assert pool.active_session_count == 0
    assert proxies[0] in pool._quarantine
    assert pool._quarantine[proxies[0]] == current_time + 60
    assert pool._failure_counts[proxies[0]] == 1

    # get_next should skip quarantined proxy
    assert pool.get_next() == proxies[1]

    # Advance time by 61s, quarantine should expire
    current_time += 61.0
    assert pool.get_next() == proxies[0] # Now available again

    # 2nd failure: 300s quarantine
    pool.get_for_session("session2") # gets proxies[1]
    pool.get_for_session("session3") # gets proxies[0]
    pool.report_failure("session3", base_quarantine_seconds=60)
    assert pool._quarantine[proxies[0]] == current_time + 300
    assert pool._failure_counts[proxies[0]] == 2

    # Advance time by 301s
    current_time += 301.0

    # 3rd failure: 3600s quarantine
    pool.get_next() # trigger cleanup of expired quarantine
    pool.get_for_session("session4") # gets proxies[0]
    pool.report_failure("session4", base_quarantine_seconds=60)
    assert pool._quarantine[proxies[0]] == current_time + 3600
    assert pool._failure_counts[proxies[0]] == 3

    # 4th failure: capped at 3600s
    current_time += 3601.0
    pool.get_next() # trigger cleanup of expired quarantine
    pool.get_for_session("session5") # gets proxies[0]
    pool.report_failure("session5", base_quarantine_seconds=60)
    assert pool._quarantine[proxies[0]] == current_time + 3600
    assert pool._failure_counts[proxies[0]] == 4

def test_round_robin_proxy_pool_exhausted():
    proxies = [ProxyConfig(server=f"http://proxy{i}.com") for i in range(2)]
    pool = RoundRobinProxyPool(proxies)

    pool.get_for_session("session1")
    pool.get_for_session("session2")

    pool.report_failure("session1")
    pool.report_failure("session2")

    # All proxies quarantined
    with pytest.raises(ProxyPoolExhaustedError, match="All proxies in the pool are currently quarantined"):
        pool.get_next()

def test_from_urls_and_csv():
    urls = ["http://proxy1.com", "http://user:pwd@proxy2.com"]
    pool1 = RoundRobinProxyPool.from_urls(urls)
    assert len(pool1._proxies) == 2

    csv = "http://proxy1.com, http://user:pwd@proxy2.com"
    pool2 = RoundRobinProxyPool.from_csv(csv)
    assert len(pool2._proxies) == 2

    assert RoundRobinProxyPool.from_csv("   ") is None
