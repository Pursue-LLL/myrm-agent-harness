from myrm_agent_harness.toolkits.llms.reliability.jittered_backoff import (
    calculate_adaptive_jittered_delay,
    calculate_jittered_delay,
    is_paas_overload_error,
    paas_overload_retry_ceiling,
)


def test_calculate_jittered_delay_base_case() -> None:
    # Attempt 1 -> exponent 0 -> base_delay 2.0
    # Jitter range is [0, 0.5 * 2.0] = [0, 1.0]
    delay = calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5)
    assert 2.0 <= delay <= 3.0


def test_calculate_jittered_delay_exponential() -> None:
    # Attempt 3 -> exponent 2 -> base_delay 2.0 * 4 = 8.0
    # Jitter range is [0, 0.5 * 8.0] = [0, 4.0]
    delay = calculate_jittered_delay(3, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5)
    assert 8.0 <= delay <= 12.0


def test_calculate_jittered_delay_max_cap() -> None:
    # Attempt 10 -> base_delay 2.0 * 512 = 1024 -> capped at 60.0
    # Jitter range is [0, 0.5 * 60.0] = [0, 30.0]
    delay = calculate_jittered_delay(10, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5)
    assert 60.0 <= delay <= 90.0


def test_calculate_jittered_delay_retry_after() -> None:
    # Attempt 1 -> base_delay 2.0, but retry_after is 15.0
    # Jitter range is [0, 0.5 * 15.0] = [0, 7.5]
    delay = calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5, retry_after=15.0)
    assert 15.0 <= delay <= 22.5


def test_provider_stated_wait_beyond_cap_is_honored_exactly() -> None:
    # The cap bounds our own backoff, never the provider's stated wait.
    for _ in range(50):
        delay = calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5, retry_after=240.0)
        assert delay == 240.0


def test_calculate_jittered_delay_decorrelation() -> None:
    # Multiple calls should yield different jitter even if called rapidly
    # Since it uses tick counter and XOR
    delays = [calculate_jittered_delay(1, base_delay=2.0, max_delay=60.0, jitter_ratio=0.5) for _ in range(100)]
    # Ensure they are not all exactly the same
    assert len(set(delays)) > 50


def test_is_paas_overload_error_detection() -> None:
    class CustomError(Exception):
        def __init__(self, msg: str, status_code: int = 429) -> None:
            super().__init__(msg)
            self.status_code = status_code

    paas_err = CustomError("Error code 1305: Engine temporarily overloaded, queue full", status_code=429)
    assert is_paas_overload_error(paas_err) is True

    generic_429 = CustomError("Rate limit exceeded. Try again in 2s", status_code=429)
    assert is_paas_overload_error(generic_429) is False

    err_529 = CustomError("temporarily_overloaded 1305", status_code=529)
    assert is_paas_overload_error(err_529) is True

    none_err = None
    assert is_paas_overload_error(none_err) is False


def test_calculate_adaptive_jittered_delay_paas_ladder() -> None:
    class MockPaasOverloadError(Exception):
        def __init__(self) -> None:
            super().__init__("Error 1305: temporarily overloaded")
            self.status_code = 429

    err = MockPaasOverloadError()

    # Short attempts (1, 2)
    delay1, label1 = calculate_adaptive_jittered_delay(1, error=err, short_attempts=2)
    assert label1 == "paas_1305_short"
    assert 2.0 <= delay1 <= 3.0

    delay2, label2 = calculate_adaptive_jittered_delay(2, error=err, short_attempts=2)
    assert label2 == "paas_1305_short"
    assert 4.0 <= delay2 <= 6.0

    # Long backoff ladder (attempt 3 -> 30s base, attempt 4 -> 60s base)
    delay3, label3 = calculate_adaptive_jittered_delay(3, error=err, short_attempts=2)
    assert label3 == "paas_1305_long"
    # base 30s, jitter_ratio=0.2 -> 30.0 <= delay <= 36.0
    assert 30.0 <= delay3 <= 36.0

    delay4, label4 = calculate_adaptive_jittered_delay(4, error=err, short_attempts=2)
    assert label4 == "paas_1305_long"
    assert 60.0 <= delay4 <= 72.0

    # Ceiling calculation
    ceiling = paas_overload_retry_ceiling(short_attempts=2)
    assert ceiling == 2 + 4 + 1  # 7 attempts
