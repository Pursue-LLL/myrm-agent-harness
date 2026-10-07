from __future__ import annotations

from myrm_agent_harness.runtime.context import (
    JsonMergePatchGovernor,
    PrebuiltStateSchemaKind,
    RetroactiveProbeQuery,
    SkillStateConstantPromptEngine,
    apply_rfc7386_merge_patch,
    get_default_schema_state,
)


def test_rfc7386_merge_patch_semantics() -> None:
    """Test RFC 7386 JSON Merge Patch deep recursive merge, key deletion, and immutability."""
    target = {
        "title": "Old Project",
        "author": "Alice",
        "config": {"debug": True, "timeout": 30, "nested": {"level": 1}},
        "tags": ["alpha", "beta"],
    }

    # Patch: modify title, delete author (val is None), recursively update config, replace tags
    patch = {
        "title": "New Project",
        "author": None,
        "config": {"timeout": 60, "nested": {"level": 2}},
        "tags": ["gamma"],
        "extra_info": "new_entry",
    }

    result = apply_rfc7386_merge_patch(target, patch)

    # Verify original is untouched (pure function immutability)
    assert target["title"] == "Old Project"
    assert target["author"] == "Alice"
    assert target["config"]["timeout"] == 30

    # Verify patched results
    assert result["title"] == "New Project"
    assert "author" not in result
    assert result["config"] == {"debug": True, "timeout": 60, "nested": {"level": 2}}
    assert result["tags"] == ["gamma"]
    assert result["extra_info"] == "new_entry"


def test_five_prebuilt_schemas_and_governor_validation() -> None:
    """Test all 5 prebuilt schemas and governor validation gate."""
    for schema_kind in PrebuiltStateSchemaKind:
        initial = get_default_schema_state(schema_kind)
        assert isinstance(initial, dict)
        assert len(initial) > 0

    governor = JsonMergePatchGovernor(allowed_schema=PrebuiltStateSchemaKind.SOFTWARE_REPOSITORY)
    curr_state = get_default_schema_state(PrebuiltStateSchemaKind.SOFTWARE_REPOSITORY)

    # Valid patch
    valid_patch = {"current_branch": "feature/cache-engine", "ci_matrix_status": {"build": "passed"}}
    merged, ok, err = governor.safe_atomic_apply(curr_state, valid_patch)
    assert ok is True
    assert err is None
    assert merged["current_branch"] == "feature/cache-engine"
    assert merged["ci_matrix_status"]["build"] == "passed"

    # Invalid patch violating schema rule (ci_matrix_status must be dict)
    invalid_patch = {"ci_matrix_status": "not_a_dict"}
    state_after_fail, ok2, err2 = governor.safe_atomic_apply(curr_state, invalid_patch)
    assert ok2 is False
    assert "ci_matrix_status must be a dictionary" in (err2 or "")
    assert state_after_fail == curr_state


def test_governor_wrapper_and_markdown_sanitization() -> None:
    """Test resilience against smaller LLM syntax wrappers like markdown fences and $set."""
    governor = JsonMergePatchGovernor()
    curr_state = {"shelf_1": "empty", "shelf_2": "apple"}

    # Markdown fence payload
    fenced_payload = '```json\n{"$set": {"shelf_1": "orange"}}\n```'
    merged, ok, err = governor.safe_atomic_apply(curr_state, fenced_payload)
    assert ok is True
    assert err is None
    assert merged["shelf_1"] == "orange"
    assert merged["shelf_2"] == "apple"

    # Malformed JSON handling
    _, bad_ok, bad_err = governor.safe_atomic_apply(curr_state, "{invalid_json")
    assert bad_ok is False
    assert "Malformed patch payload" in (bad_err or "")


def test_constant_prompt_o1_complexity_over_50_steps() -> None:
    """Simulate 50 steps: verify prompt length stays strictly O(1) constant instead of O(T^2)."""
    spec = "You are a warehouse automation agent. Maintain explicit shelf inventory."
    engine = SkillStateConstantPromptEngine(
        spec_prompt=spec,
        schema_kind=PrebuiltStateSchemaKind.RESOURCE_INVENTORY,
    )

    prompt_lengths: list[int] = []

    for step_i in range(1, 51):
        action = f"move_item_to_slot_{step_i}"
        obs = f"Sensor reading at step {step_i}: Slot {step_i} item transfer completed with status 200 OK."
        patch = {
            "allocated_slots": {f"slot_{step_i}": f"package_{step_i}"},
            "quota_limits": {"used_slots": step_i},
        }

        prompt_tuple, ok, err = engine.step(action, obs, patch)
        assert ok is True
        assert err is None

        rendered = prompt_tuple.render_prompt()
        prompt_lengths.append(len(rendered))

    # All prompts in the last 10 steps should be roughly constant length (O(1) complexity)
    assert engine.step_counter == 50
    # Difference between step 40 and step 50 is strictly bounded (O(1)), far away from O(T^2) explosion
    diff_40_50 = abs(prompt_lengths[49] - prompt_lengths[39])
    assert diff_40_50 < 300  # Stays bounded within trivial metadata size difference


def test_zero_step_environment_mutation_self_healing() -> None:
    """Test 0-step self-healing when external environment silently mutates."""
    engine = SkillStateConstantPromptEngine(
        spec_prompt="Maintain git workspace",
        schema_kind=PrebuiltStateSchemaKind.SOFTWARE_REPOSITORY,
    )

    # Run 3 steps normally
    engine.step("git_checkout", "Switched to branch dev", {"current_branch": "dev"})
    engine.step("edit_file", "Edited main.py", {"modified_files": ["main.py"]})

    prompt_before = engine.get_constant_prompt()
    assert prompt_before.state_table["current_branch"] == "dev"
    assert prompt_before.state_table["modified_files"] == ["main.py"]

    # External emergency reset occurs outside agent control
    mutation_patch = {"current_branch": "main", "modified_files": []}
    prompt_after = engine.force_environment_mutation(
        mutation_patch=mutation_patch,
        mutation_reason="Host branch forcibly reset by CI webhook",
    )

    # Instantly healed at 0 step with no stale historical hallucinations
    assert prompt_after.state_table["current_branch"] == "main"
    assert prompt_after.state_table["modified_files"] == []
    assert "[Environment Mutation Detected]" in (prompt_after.latest_observation or "")


def test_immutable_audit_log_and_retroactive_observation_probe() -> None:
    """Test dual-track execution/audit logging and retroactive observation probe recovery."""
    engine = SkillStateConstantPromptEngine(
        spec_prompt="Reverse engineering assistant",
        schema_kind=PrebuiltStateSchemaKind.REVERSE_ENGINEERING,
        max_observation_chars=100,
    )

    # Step 1: Tool emits a large raw telemetry output containing a key secret token
    raw_noisy_telemetry = "DEBUG " * 50 + "SECRET_KEY_XYZ_98765 " + "TELEMETRY " * 50
    engine.step("run_disassembly", raw_noisy_telemetry, {"target_binaries": ["vuln_service"]})

    # Step 2: Next tool execution
    engine.step("check_port", "Port 8080 open", {"active_workdir": "/opt/app"})

    # Forward-facing execution track has truncated observation for step 1 and step 2 replaced observation
    current_prompt = engine.get_constant_prompt()
    assert current_prompt.latest_observation == "Port 8080 open"
    assert "SECRET_KEY_XYZ_98765" not in (current_prompt.latest_observation or "")

    # But background audit track retains full unclipped raw telemetry
    audit_records = engine.audit_log
    assert len(audit_records) == 2
    assert "SECRET_KEY_XYZ_98765" in audit_records[0].observation_raw

    # At step 3, agent realizes it needs the forgotten token: invoke retroactive probe!
    probe_query = RetroactiveProbeQuery(keyword="SECRET_KEY")
    probe_res = engine.probe_audit_log(probe_query)
    assert len(probe_res.matched_records) == 1
    assert probe_res.matched_records[0].step_index == 1

    # Reconcile retrieved secret back into explicit state table
    recovered_patch = {"discovered_flags": ["FLAG{SECRET_KEY_XYZ_98765}"]}
    reconciled_prompt = engine.reconcile_retroactive_observation(recovered_patch)
    assert reconciled_prompt.state_table["discovered_flags"] == ["FLAG{SECRET_KEY_XYZ_98765}"]
