from myrm_agent_harness.agent.skills.optimization.prometheus_metrics import (
    circuit_breaker_tripped,
    dlq_size,
    llm_cost_usd,
    llm_tokens,
    optimization_failed,
    optimization_queue_size,
    optimization_success,
    optimization_total,
    record_llm_cost,
    record_llm_tokens,
    record_optimization_failure,
    record_optimization_start,
    record_optimization_success,
    update_circuit_breaker_count,
    update_dlq_size,
    update_queue_size,
)


def test_record_optimization_start() -> None:
    before = optimization_total.labels(skill_id="test_skill", status="queued")._value.get()
    record_optimization_start("test_skill")
    after = optimization_total.labels(skill_id="test_skill", status="queued")._value.get()
    assert after == before + 1


def test_record_optimization_success() -> None:
    before_total = optimization_total.labels(skill_id="test_skill", status="success")._value.get()
    before_success = optimization_success.labels(skill_id="test_skill", version="2")._value.get()

    record_optimization_success("test_skill", 2, 1.5)

    after_total = optimization_total.labels(skill_id="test_skill", status="success")._value.get()
    after_success = optimization_success.labels(skill_id="test_skill", version="2")._value.get()

    assert after_total == before_total + 1
    assert after_success == before_success + 1


def test_record_optimization_failure() -> None:
    before_total = optimization_total.labels(skill_id="test_skill", status="failed")._value.get()
    before_failed = optimization_failed.labels(skill_id="test_skill", reason="timeout")._value.get()

    record_optimization_failure("test_skill", "timeout", 2.0)

    after_total = optimization_total.labels(skill_id="test_skill", status="failed")._value.get()
    after_failed = optimization_failed.labels(skill_id="test_skill", reason="timeout")._value.get()

    assert after_total == before_total + 1
    assert after_failed == before_failed + 1


def test_update_gauges() -> None:
    update_queue_size(5)
    assert optimization_queue_size._value.get() == 5

    update_circuit_breaker_count(2)
    assert circuit_breaker_tripped._value.get() == 2

    update_dlq_size(10)
    assert dlq_size._value.get() == 10


def test_record_llm_metrics() -> None:
    before_cost = llm_cost_usd.labels(skill_id="test_skill", model="gpt-4")._value.get()
    before_prompt = llm_tokens.labels(skill_id="test_skill", model="gpt-4", token_type="prompt")._value.get()
    before_completion = llm_tokens.labels(skill_id="test_skill", model="gpt-4", token_type="completion")._value.get()

    record_llm_cost("test_skill", "gpt-4", 0.05)
    record_llm_tokens("test_skill", "gpt-4", 100, 50)

    after_cost = llm_cost_usd.labels(skill_id="test_skill", model="gpt-4")._value.get()
    after_prompt = llm_tokens.labels(skill_id="test_skill", model="gpt-4", token_type="prompt")._value.get()
    after_completion = llm_tokens.labels(skill_id="test_skill", model="gpt-4", token_type="completion")._value.get()

    assert after_cost == before_cost + 0.05
    assert after_prompt == before_prompt + 100
    assert after_completion == before_completion + 50
