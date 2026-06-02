from myrm_agent_harness.toolkits.llms.reliability.jittered_backoff import calculate_jittered_delay


def test_calculate_jittered_delay_base_case():
    # Attempt 1 -> exponent 0 -> base_delay 2.0
    # Jitter range is [0, 0.5 * 2.0] = [0, 1.0]
    delay = calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5)
    assert 2.0 <= delay <= 3.0


def test_calculate_jittered_delay_exponential():
    # Attempt 3 -> exponent 2 -> base_delay 2.0 * 4 = 8.0
    # Jitter range is [0, 0.5 * 8.0] = [0, 4.0]
    delay = calculate_jittered_delay(3, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5)
    assert 8.0 <= delay <= 12.0


def test_calculate_jittered_delay_max_cap():
    # Attempt 10 -> base_delay 2.0 * 512 = 1024 -> capped at 60.0
    # Jitter range is [0, 0.5 * 60.0] = [0, 30.0]
    delay = calculate_jittered_delay(10, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5)
    assert 60.0 <= delay <= 90.0


def test_calculate_jittered_delay_retry_after():
    # Attempt 1 -> base_delay 2.0, but retry_after is 15.0
    # Jitter range is [0, 0.5 * 15.0] = [0, 7.5]
    delay = calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5, retry_after=15.0)
    assert 15.0 <= delay <= 22.5


def test_calculate_jittered_delay_decorrelation():
    # Multiple calls should yield different jitter even if called rapidly
    # Since it uses tick counter and XOR
    delays = [calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5) for _ in range(100)]
    # Ensure they are not all exactly the same
    assert len(set(delays)) > 50
