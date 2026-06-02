import pytest

from myrm_agent_harness.agent.skills.optimization.health_check import (
    HealthCheckResult,
    aggregate_health_checks,
    validate_health_check_result,
)


class MockHealthyComponent:
    async def health_check(self) -> HealthCheckResult:
        return {"healthy": True, "component": "mock_healthy", "extra": "data"}


class MockUnhealthyComponent:
    async def health_check(self) -> HealthCheckResult:
        return {"healthy": False, "component": "mock_unhealthy", "error": "Something went wrong"}


class MockExceptionComponent:
    async def health_check(self) -> HealthCheckResult:
        raise ValueError("Critical failure")


@pytest.mark.asyncio
async def test_aggregate_health_checks_all_healthy() -> None:
    components = {
        "comp1": MockHealthyComponent(),
        "comp2": MockHealthyComponent(),
    }

    result = await aggregate_health_checks(components)

    assert result["healthy"] is True
    assert result["component"] == "aggregated"
    assert result["total_components"] == 2
    assert result["healthy_components"] == 2
    assert "comp1" in result["components"]
    assert "comp2" in result["components"]


@pytest.mark.asyncio
async def test_aggregate_health_checks_strict_mode() -> None:
    components = {
        "comp1": MockHealthyComponent(),
        "comp2": MockUnhealthyComponent(),
    }

    result = await aggregate_health_checks(components, strict=True)

    assert result["healthy"] is False
    assert result["healthy_components"] == 1
    assert result["components"]["comp2"]["healthy"] is False


@pytest.mark.asyncio
async def test_aggregate_health_checks_non_strict_mode() -> None:
    components = {
        "comp1": MockHealthyComponent(),
        "comp2": MockUnhealthyComponent(),
    }

    result = await aggregate_health_checks(components, strict=False)

    assert result["healthy"] is True  # At least one is healthy
    assert result["healthy_components"] == 1


@pytest.mark.asyncio
async def test_aggregate_health_checks_with_exception() -> None:
    components = {
        "comp1": MockExceptionComponent(),
    }

    result = await aggregate_health_checks(components)

    assert result["healthy"] is False
    assert result["components"]["comp1"]["healthy"] is False
    assert "Critical failure" in result["components"]["comp1"]["error"]


def test_validate_health_check_result() -> None:
    # Valid results
    assert validate_health_check_result({"healthy": True, "component": "test"}) is True
    assert validate_health_check_result({"healthy": False, "component": "test", "error": "msg"}) is True

    # Invalid results
    assert validate_health_check_result("not a dict") is False
    assert validate_health_check_result({"component": "test"}) is False  # Missing healthy
    assert validate_health_check_result({"healthy": "yes", "component": "test"}) is False  # healthy not bool
    assert validate_health_check_result({"healthy": True}) is False  # Missing component
    assert validate_health_check_result({"healthy": True, "component": 123}) is False  # component not str
    assert (
        validate_health_check_result({"healthy": False, "component": "test"}) is False
    )  # Missing error when unhealthy
