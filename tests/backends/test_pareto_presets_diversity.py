"""Tests verifying provider diversity on Pareto preset YAML configurations."""

from __future__ import annotations

import glob
import os
import yaml
import pytest

from myrm_agent_harness.backends.profiles.diversity_lint import (
    ModelSelectionSlot,
    validate_provider_diversity,
)

PREBUILT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../myrm-agent/myrm-agent-server/assets/prebuilt_agents")
)


def test_pareto_presets_yaml_provider_diversity() -> None:
    yaml_files = glob.glob(os.path.join(PREBUILT_DIR, "*.yaml"))
    assert len(yaml_files) > 0, f"No yaml files found in {PREBUILT_DIR}"

    pareto_found = 0
    for file_path in yaml_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not data or not data.get("is_pareto_preset"):
                continue

            pareto_found += 1
            slots: list[ModelSelectionSlot] = []

            # 1. Routing config slots
            routing = data.get("routing_config", {})
            if routing.get("light_model"):
                slots.append(
                    ModelSelectionSlot(
                        provider_id=routing["light_model"]["provider"],
                        model=routing["light_model"]["model"],
                        slot_name="light_model",
                    )
                )
            if routing.get("reasoning_model"):
                slots.append(
                    ModelSelectionSlot(
                        provider_id=routing["reasoning_model"]["provider"],
                        model=routing["reasoning_model"]["model"],
                        slot_name="reasoning_model",
                    )
                )

            # 2. MoA overlay reference model slots
            moa = data.get("moa_overlay", {})
            for ref in moa.get("reference_model_selections", []):
                slots.append(
                    ModelSelectionSlot(
                        provider_id=ref.get("providerId") or ref.get("provider", ""),
                        model=ref.get("model", ""),
                        slot_name="moa_reference",
                        reasoning_effort=ref.get("reasoning_effort"),
                    )
                )

            # 3. Team member model slots
            for member in data.get("members", []):
                m_sel = member.get("model_selection", {})
                if m_sel.get("provider") and m_sel.get("model"):
                    slots.append(
                        ModelSelectionSlot(
                            provider_id=m_sel["provider"],
                            model=m_sel["model"],
                            slot_name=f"member_{member.get('role', 'unknown')}",
                        )
                    )

            # Validate that every Pareto preset maintains at least 2 distinct root vendors
            res = validate_provider_diversity(slots, min_distinct_vendors=2)
            assert res.is_valid, (
                f"Pareto preset {os.path.basename(file_path)} failed diversity check: "
                f"{res.reason}. Vendors: {res.distinct_vendors}"
            )
            assert res.distinct_vendor_count >= 2

    assert pareto_found >= 3, f"Expected at least 3 Pareto presets, found {pareto_found}"
