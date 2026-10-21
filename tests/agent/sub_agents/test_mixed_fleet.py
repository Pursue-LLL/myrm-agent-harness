import pytest

from myrm_agent_harness.agent.sub_agents.mixed_fleet import (
    DispatchHandoffRequest,
    FleetExecutionStatusEnum,
    FleetRoleEnum,
    MixedFleetCoordinator,
    MixedFleetError,
    MixedFleetHandoffNotFoundError,
    MixedFleetOfflineError,
)


def test_get_or_create_fleet() -> None:
    coordinator = MixedFleetCoordinator()
    chat_id = "chat-mixed-001"

    local_node, remote_node = coordinator.get_or_create_fleet(chat_id)
    assert local_node.role == FleetRoleEnum.LOCAL_BRAIN
    assert local_node.is_online is True
    assert "local_memory" in local_node.supported_capabilities

    assert remote_node.role == FleetRoleEnum.REMOTE_EXECUTOR
    assert remote_node.is_online is True
    assert "long_running_jobs" in remote_node.supported_capabilities


def test_dispatch_to_remote_success() -> None:
    coordinator = MixedFleetCoordinator()
    chat_id = "chat-mixed-002"

    req = DispatchHandoffRequest(
        chat_id=chat_id,
        task_instruction="Run 24/7 web scraper and compile product catalog",
        context_files=["config/scraper_rules.json", "data/seed_urls.txt"],
    )
    manifest = coordinator.dispatch_to_remote(req)
    assert manifest.manifest_id.startswith("mf-handoff-")
    assert manifest.chat_id == chat_id
    assert manifest.execution_status == FleetExecutionStatusEnum.DISPATCHED
    assert manifest.source_role == FleetRoleEnum.LOCAL_BRAIN
    assert manifest.target_role == FleetRoleEnum.REMOTE_EXECUTOR

    # Markdown format check
    assert "# Mixed Fleet Handoff Manifest" in manifest.handoff_markdown
    assert "scraper_rules.json" in manifest.handoff_markdown
    assert "Run 24/7 web scraper" in manifest.handoff_markdown


def test_dispatch_empty_instruction_error() -> None:
    coordinator = MixedFleetCoordinator()
    with pytest.raises(MixedFleetError, match="Task instruction cannot be empty"):
        coordinator.dispatch_to_remote(
            DispatchHandoffRequest(
                chat_id="chat-mixed-003",
                task_instruction="   ",
            )
        )


def test_dispatch_offline_error() -> None:
    coordinator = MixedFleetCoordinator()
    chat_id = "chat-mixed-004"
    coordinator.update_heartbeat(chat_id, FleetRoleEnum.REMOTE_EXECUTOR, is_online=False)

    with pytest.raises(MixedFleetOfflineError, match="currently offline"):
        coordinator.dispatch_to_remote(
            DispatchHandoffRequest(
                chat_id=chat_id,
                task_instruction="Heavy build task",
            )
        )


def test_sync_from_remote_and_completion() -> None:
    coordinator = MixedFleetCoordinator()
    chat_id = "chat-mixed-005"
    manifest = coordinator.dispatch_to_remote(
        DispatchHandoffRequest(
            chat_id=chat_id,
            task_instruction="Async benchmark job",
        )
    )

    synced = coordinator.sync_from_remote(chat_id, manifest.manifest_id)
    assert synced.synced_at is not None

    completed = coordinator.complete_remote_execution(
        manifest.manifest_id,
        output_summary="Benchmark finished with 1200 req/s throughput",
    )
    assert completed.execution_status == FleetExecutionStatusEnum.COMPLETED
    assert completed.output_summary == "Benchmark finished with 1200 req/s throughput"

    # Cross-chat sync violation
    with pytest.raises(MixedFleetError, match="does not belong to chat"):
        coordinator.sync_from_remote("another-chat", manifest.manifest_id)


def test_fail_remote_execution() -> None:
    coordinator = MixedFleetCoordinator()
    chat_id = "chat-mixed-006"
    manifest = coordinator.dispatch_to_remote(
        DispatchHandoffRequest(
            chat_id=chat_id,
            task_instruction="Compilation task",
        )
    )

    failed = coordinator.fail_remote_execution(
        manifest.manifest_id,
        error_detail="Compiler OOM in container",
    )
    assert failed.execution_status == FleetExecutionStatusEnum.FAILED
    assert failed.error_detail == "Compiler OOM in container"

    # Non-existent manifest lookup
    with pytest.raises(MixedFleetHandoffNotFoundError):
        coordinator.get_manifest("non-existent-manifest")


def test_update_heartbeat_and_snapshot() -> None:
    coordinator = MixedFleetCoordinator()
    chat_id = "chat-mixed-007"

    coordinator.dispatch_to_remote(
        DispatchHandoffRequest(chat_id=chat_id, task_instruction="Task 1")
    )
    coordinator.dispatch_to_remote(
        DispatchHandoffRequest(chat_id=chat_id, task_instruction="Task 2")
    )

    snapshot = coordinator.get_fleet_snapshot(chat_id)
    assert snapshot.total_handoffs == 2
    assert snapshot.active_manifest is not None
    assert snapshot.active_manifest.task_instruction == "Task 2"

    coordinator.update_heartbeat(chat_id, FleetRoleEnum.LOCAL_BRAIN, is_online=True)
    refreshed_snapshot = coordinator.get_fleet_snapshot(chat_id)
    assert refreshed_snapshot.local_brain.is_online is True
