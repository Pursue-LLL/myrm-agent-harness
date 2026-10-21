"""Unit tests for ZeroReplayProtocolEngine and snapshot models."""


from myrm_agent_harness.agent.streaming.zero_replay import (
    LiveStreamFilterConfig,
    SessionAtomicSnapshot,
    ZeroReplayProtocolEngine,
)


def test_compile_atomic_snapshot_defaults() -> None:
    engine = ZeroReplayProtocolEngine()
    session_id = "sess_zero_001"

    snapshot = engine.compile_atomic_snapshot(
        session_id=session_id,
        status="running",
        leaf_entry_id="msg_leaf_10",
        active_tool_calls=[{"call_id": "call_1", "tool_name": "web_search"}],
        message_count=10,
        latest_turn_summary="Searching for weather reports",
    )

    assert isinstance(snapshot, SessionAtomicSnapshot)
    assert snapshot.session_id == session_id
    assert snapshot.status == "running"
    assert snapshot.state_version == 1
    assert snapshot.leaf_entry_id == "msg_leaf_10"
    assert len(snapshot.active_tool_calls) == 1
    assert snapshot.message_count == 10
    assert snapshot.epoch_id != ""


def test_monotonic_state_version_and_epoch_reset() -> None:
    engine = ZeroReplayProtocolEngine()
    session_id = "sess_zero_002"

    epoch_1 = engine.get_or_create_epoch(session_id)
    v1 = engine.get_current_version(session_id)
    assert v1 == 1

    v2 = engine.increment_state_version(session_id)
    assert v2 == 2

    v3 = engine.increment_state_version(session_id)
    assert v3 == 3

    # Reset epoch resets version back to 1 and changes epoch_id
    epoch_2 = engine.reset_epoch(session_id)
    assert epoch_2 != epoch_1
    assert engine.get_current_version(session_id) == 1


def test_live_stream_filter_eligibility() -> None:
    snapshot_time = 10000.0
    client_version = 5

    config = LiveStreamFilterConfig(
        client_snapshot_timestamp_ms=snapshot_time,
        client_state_version=client_version,
        allow_equal_timestamp=False,
    )

    # 1. Past event version -> rejected
    assert not ZeroReplayProtocolEngine.is_event_eligible_for_live_stream(
        event_timestamp_ms=10500.0,
        event_version=4,
        filter_config=config,
    )

    # 2. Same event version as snapshot -> rejected (Zero-Replay invariant)
    assert not ZeroReplayProtocolEngine.is_event_eligible_for_live_stream(
        event_timestamp_ms=10500.0,
        event_version=5,
        filter_config=config,
    )

    # 3. Future version but past/stale timestamp -> rejected
    assert not ZeroReplayProtocolEngine.is_event_eligible_for_live_stream(
        event_timestamp_ms=9999.0,
        event_version=6,
        filter_config=config,
    )

    # 4. Strictly fresh live event -> accepted
    assert ZeroReplayProtocolEngine.is_event_eligible_for_live_stream(
        event_timestamp_ms=10001.0,
        event_version=6,
        filter_config=config,
    )


def test_reconnect_handshake_evaluation() -> None:
    engine = ZeroReplayProtocolEngine()
    session_id = "sess_zero_003"
    engine.increment_state_version(session_id)  # version 2

    server_snapshot = engine.compile_atomic_snapshot(session_id=session_id)

    # Case 1: Matching epoch and version <= server version -> continue live
    decision_valid = ZeroReplayProtocolEngine.evaluate_handshake(
        client_epoch_id=server_snapshot.epoch_id,
        client_version=1,
        server_snapshot=server_snapshot,
    )
    assert decision_valid == "continue_live"

    # Case 2: Mismatched epoch (server restarted or branch switched) -> reload snapshot
    decision_stale_epoch = ZeroReplayProtocolEngine.evaluate_handshake(
        client_epoch_id="stale_epoch_999",
        client_version=1,
        server_snapshot=server_snapshot,
    )
    assert decision_stale_epoch == "require_full_snapshot_reload"

    # Case 3: Client version phantom ahead of server -> reload snapshot
    decision_future_version = ZeroReplayProtocolEngine.evaluate_handshake(
        client_epoch_id=server_snapshot.epoch_id,
        client_version=99,
        server_snapshot=server_snapshot,
    )
    assert decision_future_version == "require_full_snapshot_reload"
