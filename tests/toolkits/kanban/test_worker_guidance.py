"""Tests for get_worker_lifecycle_guidance function."""

from myrm_agent_harness.toolkits.kanban import get_worker_lifecycle_guidance


class TestWorkerLifecycleGuidance:
    """Verify guidance text generation with various parameters."""

    def test_default_params(self) -> None:
        result = get_worker_lifecycle_guidance()
        assert "[Kanban Worker Lifecycle]" in result
        assert "kanban_complete" in result
        assert "kanban_block" in result
        assert "kanban_heartbeat" in result
        assert "Prior attempts" in result
        assert "runtime limit" not in result

    def test_custom_zombie_timeout(self) -> None:
        result = get_worker_lifecycle_guidance(zombie_timeout_seconds=200)
        assert "every ~100s" in result

    def test_heartbeat_minimum_30s(self) -> None:
        result = get_worker_lifecycle_guidance(zombie_timeout_seconds=40)
        assert "every ~30s" in result

    def test_max_runtime_included(self) -> None:
        result = get_worker_lifecycle_guidance(max_runtime_seconds=600)
        assert "runtime limit of 600s" in result

    def test_max_runtime_none_excluded(self) -> None:
        result = get_worker_lifecycle_guidance(max_runtime_seconds=None)
        assert "runtime limit" not in result

    def test_output_starts_with_newlines(self) -> None:
        result = get_worker_lifecycle_guidance()
        assert result.startswith("\n\n[Kanban Worker Lifecycle]")

    def test_reasonable_length(self) -> None:
        result = get_worker_lifecycle_guidance()
        assert 300 < len(result) < 2000

    def test_zero_zombie_timeout_uses_minimum(self) -> None:
        result = get_worker_lifecycle_guidance(zombie_timeout_seconds=0)
        assert "every ~30s" in result

    def test_very_large_zombie_timeout(self) -> None:
        result = get_worker_lifecycle_guidance(zombie_timeout_seconds=7200)
        assert "every ~3600s" in result

    def test_max_runtime_zero_excluded(self) -> None:
        result = get_worker_lifecycle_guidance(max_runtime_seconds=0)
        assert "runtime limit" not in result

    def test_both_params_combined(self) -> None:
        result = get_worker_lifecycle_guidance(
            zombie_timeout_seconds=300, max_runtime_seconds=1800
        )
        assert "every ~150s" in result
        assert "runtime limit of 1800s" in result

    def test_return_type_is_str(self) -> None:
        result = get_worker_lifecycle_guidance()
        assert isinstance(result, str)
