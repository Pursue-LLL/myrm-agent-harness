"""Unit tests for Meta-Harness 4-Mechanism plateau diagnosis engine."""

from myrm_agent_harness.eval.plateau import (
    PlateauDiagnosis,
    PlateauMechanism,
    diagnose_plateau,
)


def test_diagnose_plateau_hard_subset_bottleneck() -> None:
    diag = diagnose_plateau(
        total_cases=20,
        discordant_count=0,
        base_pass_rate=0.5,
        cand_pass_rate=0.5,
        p_value=1.0,
        ci_crosses_zero=True,
        regressions_count=0,
    )
    assert diag.mechanism == PlateauMechanism.HARD_SUBSET_BOTTLENECK
    assert diag.suggested_action == "expand_tools_or_context"
    d = diag.to_dict()
    assert d["mechanism"] == "hard_subset_bottleneck"
    assert "Hard Subset Bottleneck" in str(d["title"])


def test_diagnose_plateau_capability_saturation() -> None:
    diag = diagnose_plateau(
        total_cases=50,
        discordant_count=6,
        base_pass_rate=0.92,
        cand_pass_rate=0.94,
        p_value=0.20,
        ci_crosses_zero=True,
        regressions_count=1,
    )
    assert diag.mechanism == PlateauMechanism.CAPABILITY_SATURATION
    assert diag.suggested_action == "introduce_hard_benchmark"


def test_diagnose_plateau_insufficient_power_small_total() -> None:
    diag = diagnose_plateau(
        total_cases=8,
        discordant_count=3,
        base_pass_rate=0.5,
        cand_pass_rate=0.75,
        p_value=0.25,
        ci_crosses_zero=True,
        regressions_count=0,
    )
    assert diag.mechanism == PlateauMechanism.INSUFFICIENT_POWER
    assert diag.suggested_action == "increase_trials_or_dataset"


def test_diagnose_plateau_insufficient_power_low_discordant() -> None:
    diag = diagnose_plateau(
        total_cases=30,
        discordant_count=3,
        base_pass_rate=0.6,
        cand_pass_rate=0.67,
        p_value=0.25,
        ci_crosses_zero=True,
        regressions_count=0,
    )
    assert diag.mechanism == PlateauMechanism.INSUFFICIENT_POWER
    assert diag.suggested_action == "increase_trials_or_dataset"


def test_diagnose_plateau_cross_model_divergence() -> None:
    diag = diagnose_plateau(
        total_cases=40,
        discordant_count=10,
        base_pass_rate=0.6,
        cand_pass_rate=0.65,
        p_value=0.35,
        ci_crosses_zero=True,
        regressions_count=3,
    )
    assert diag.mechanism == PlateauMechanism.CROSS_MODEL_DIVERGENCE
    assert diag.suggested_action == "reject_and_investigate_regressions"


def test_diagnose_plateau_none_valid_signal() -> None:
    diag = diagnose_plateau(
        total_cases=50,
        discordant_count=12,
        base_pass_rate=0.6,
        cand_pass_rate=0.8,
        p_value=0.01,
        ci_crosses_zero=False,
        regressions_count=0,
    )
    assert diag.mechanism == PlateauMechanism.NONE
    assert diag.suggested_action == "proceed_with_gate"
