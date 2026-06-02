from myrm_agent_harness.agent.skills.evolution.utils.enhanced_schema import (
    COMMON_TRAPS,
    COMMON_VERIFICATIONS,
    SkillTrap,
    VerificationStep,
    get_trap_description,
    get_verification_description,
)


def test_skill_trap_dataclass():
    trap = SkillTrap(
        description="desc",
        severity="high",
        trigger_condition="trig",
        mitigation="mitig"
    )
    assert trap.description == "desc"
    assert trap.severity == "high"
    assert trap.trigger_condition == "trig"
    assert trap.mitigation == "mitig"
    assert trap.discovered_at is None
    assert trap.occurrence_count == 0

def test_verification_step_dataclass():
    step = VerificationStep(
        step_id="step1",
        description="desc",
        expected_output="output",
        validation_method="method"
    )
    assert step.step_id == "step1"
    assert step.description == "desc"
    assert step.expected_output == "output"
    assert step.validation_method == "method"
    assert step.is_required is True
    assert step.timeout_seconds == 30.0

def test_get_trap_description_existing():
    trap_key = "npm_install_timeout"
    assert trap_key in COMMON_TRAPS

    desc = get_trap_description(trap_key)

    trap = COMMON_TRAPS[trap_key]
    assert trap.description in desc
    assert trap.trigger_condition in desc
    assert trap.mitigation in desc

def test_get_trap_description_non_existing():
    desc = get_trap_description("invalid_trap_key_xyz")
    assert desc == ""

def test_get_trap_description_all_severities():
    # just checking that it doesn't crash on different severities
    for trap_key in COMMON_TRAPS:
        desc = get_trap_description(trap_key)
        assert desc != ""

def test_get_verification_description_existing():
    ver_key = "output_non_empty"
    assert ver_key in COMMON_VERIFICATIONS

    desc = get_verification_description(ver_key)

    ver = COMMON_VERIFICATIONS[ver_key]
    assert ver.description in desc
    assert ver.expected_output in desc
    assert ver.validation_method in desc

def test_get_verification_description_non_existing():
    desc = get_verification_description("invalid_ver_key_xyz")
    assert desc == ""

def test_get_verification_description_all():
    # just checking that it doesn't crash on different requirements
    for ver_key in COMMON_VERIFICATIONS:
        desc = get_verification_description(ver_key)
        assert desc != ""
        if COMMON_VERIFICATIONS[ver_key].is_required:
            assert "(必须)" in desc or "(必选)" in desc or "检查" in desc
        else:
            assert "(可选)" in desc or "检查" in desc
