"""Observation refinement engine for cognitive self-healing and falsification-first adaptation.

Enforces strict rules:
1. Ephemeral details (coordinates, transient ports, window IDs) are isolated locally.
2. Operational lessons that can be coded are lowered to tool behavior, not prompts.
3. Observations only promote to universal rules if replicated across >= 2 apps.
4. Empirical falsification of existing assumptions takes top priority over additions.

[INPUT]
- __future__
- re
- time
- uuid
- app_profile_registry
- profile_types

[OUTPUT]
- EphemeralInfoDetector
- ObservationRefinementEngine

[POS]
Observation refinement engine for cognitive self-healing and falsification-first adaptation.
"""

from __future__ import annotations

import re
import time
import uuid

from .app_profile_registry import AppProfileRegistry
from .profile_types import (
    AppObservation,
    AppOperatingProfile,
    FalsificationEvidence,
    FalsificationStatus,
    ObservationTier,
    PromotionEvaluationResult,
)


class EphemeralInfoDetector:
    """Detects fragile and ephemeral tokens such as absolute coordinates, window IDs, and transient ports."""

    _COORD_PATTERN = re.compile(r"(?:x\s*=\s*\d+|y\s*=\s*\d+|\b\d+\s*,\s*\d+\b|坐标|像素点)", re.IGNORECASE)
    _PORT_PATTERN = re.compile(r"(?:port\s*[:=]\s*\d{4,5}|端口\s*[:=]?\s*\d{4,5})", re.IGNORECASE)
    _WIN_ID_PATTERN = re.compile(r"(?:0x[0-9a-fA-F]{4,8}|window_id\s*[:=]\s*\d+|窗口句柄)", re.IGNORECASE)

    @classmethod
    def is_ephemeral(cls, statement: str) -> bool:
        """Evaluate if the statement contains perishable information that should not enter global rules."""
        if cls._COORD_PATTERN.search(statement):
            return True
        if cls._PORT_PATTERN.search(statement):
            return True
        return bool(cls._WIN_ID_PATTERN.search(statement))


class ObservationRefinementEngine:
    """Orchestrates observation vetting, falsification, and rule promotions across applications."""

    def __init__(self, registry: AppProfileRegistry) -> None:
        self.registry = registry

    def register_observation(
        self,
        app_id: str,
        feature_key: str,
        statement: str,
        can_convert_to_code: bool = False,
        code_hook_target: str = "",
    ) -> AppObservation:
        """Register a new observation, evaluating tier based on ephemerality and code lowering."""
        profile = self.registry.get_profile(app_id)
        if profile is None:
            profile = AppOperatingProfile(app_id=app_id, display_name=app_id)

        is_ephemeral = EphemeralInfoDetector.is_ephemeral(statement)

        if is_ephemeral:
            tier = ObservationTier.EPHEMERAL_LOCAL
        elif can_convert_to_code:
            tier = ObservationTier.CONVERTED_TO_CODE
        else:
            tier = ObservationTier.PER_APP_STABLE

        obs_id = f"obs_{uuid.uuid4().hex[:8]}"
        obs = AppObservation(
            observation_id=obs_id,
            app_id=app_id,
            feature_key=feature_key,
            statement=statement,
            tier=tier,
            status=FalsificationStatus.ACTIVE,
            is_ephemeral=is_ephemeral,
            can_convert_to_code=can_convert_to_code,
            code_hook_target=code_hook_target,
            supporting_apps=(app_id,),
            created_at=time.time(),
            updated_at=time.time(),
        )

        profile.observations[feature_key] = obs
        self.registry.register_or_update(profile)
        return obs

    def falsify_and_supersede(
        self,
        evidence: FalsificationEvidence,
        new_statement: str,
    ) -> tuple[bool, str]:
        """Falsify an existing assumption when contradicted by runtime observations.

        Falsification-first rule: Eradicating stale or mistaken rules is higher priority
        than creating new ones, preventing cascading agent failures.
        """
        profile = self.registry.get_profile(evidence.app_id)
        if profile is None:
            return False, f"Profile for '{evidence.app_id}' not found."

        existing_obs = profile.get_observation(evidence.feature_key)
        if existing_obs is None:
            return False, f"Feature key '{evidence.feature_key}' not present in profile."

        # Mark existing observation as falsified
        falsified_obs = AppObservation(
            observation_id=existing_obs.observation_id,
            app_id=existing_obs.app_id,
            feature_key=existing_obs.feature_key,
            statement=f"[FALSIFIED] {existing_obs.statement} (Reason: {evidence.contradiction_reason})",
            tier=existing_obs.tier,
            status=FalsificationStatus.FALSIFIED,
            is_ephemeral=existing_obs.is_ephemeral,
            can_convert_to_code=existing_obs.can_convert_to_code,
            code_hook_target=existing_obs.code_hook_target,
            supporting_apps=existing_obs.supporting_apps,
            created_at=existing_obs.created_at,
            updated_at=time.time(),
        )
        profile.observations[evidence.feature_key] = falsified_obs

        # Register the empirically verified replacement
        new_key = f"{evidence.feature_key}_v2"
        self.register_observation(
            app_id=evidence.app_id,
            feature_key=new_key,
            statement=new_statement,
        )

        self.registry.register_or_update(profile)
        return True, f"Feature '{evidence.feature_key}' successfully falsified and superseded by '{new_key}'."

    def evaluate_universal_promotion(
        self,
        feature_key: str,
    ) -> PromotionEvaluationResult:
        """Evaluate if an observation should promote to a universal rule across all apps.

        Rule: Must be verified across >= 2 distinct apps, must not be ephemeral,
        and must not be convertible to underlying tool code.
        """
        matching_apps: list[str] = []
        sample_obs: AppObservation | None = None

        for profile in self.registry.list_profiles():
            obs = profile.get_observation(feature_key)
            if obs and obs.status == FalsificationStatus.ACTIVE:
                matching_apps.append(profile.app_id)
                if sample_obs is None:
                    sample_obs = obs

        if sample_obs is None:
            return PromotionEvaluationResult(
                feature_key=feature_key,
                current_tier=ObservationTier.PER_APP_STABLE,
                target_tier=ObservationTier.PER_APP_STABLE,
                qualified_apps_count=0,
                qualifying_apps=(),
                is_promoted=False,
                rationale="Feature key not found in active observations across any profile.",
            )

        apps_tuple = tuple(sorted(set(matching_apps)))
        count = len(apps_tuple)

        if sample_obs.is_ephemeral:
            return PromotionEvaluationResult(
                feature_key=feature_key,
                current_tier=sample_obs.tier,
                target_tier=ObservationTier.EPHEMERAL_LOCAL,
                qualified_apps_count=count,
                qualifying_apps=apps_tuple,
                is_promoted=False,
                rationale="Ephemeral observations containing coordinates or temporary IDs cannot be promoted.",
            )

        if sample_obs.can_convert_to_code:
            code_rec = (
                f"Lower logic into tool driver hook '{sample_obs.code_hook_target}' "
                "instead of adding to prompt text."
            )
            return PromotionEvaluationResult(
                feature_key=feature_key,
                current_tier=sample_obs.tier,
                target_tier=ObservationTier.CONVERTED_TO_CODE,
                qualified_apps_count=count,
                qualifying_apps=apps_tuple,
                is_promoted=False,
                rationale="Lesson can be converted into deterministic tool code. Code-over-prompt strictly enforced.",
                recommended_code_patch=code_rec,
            )

        if count >= 2:
            # Promote observation in each supporting profile
            for app_id in apps_tuple:
                prof = self.registry.get_profile(app_id)
                if prof and feature_key in prof.observations:
                    cur = prof.observations[feature_key]
                    promoted_obs = AppObservation(
                        observation_id=cur.observation_id,
                        app_id=cur.app_id,
                        feature_key=cur.feature_key,
                        statement=cur.statement,
                        tier=ObservationTier.PROMOTED_UNIVERSAL,
                        status=cur.status,
                        is_ephemeral=False,
                        can_convert_to_code=False,
                        code_hook_target=cur.code_hook_target,
                        supporting_apps=apps_tuple,
                        created_at=cur.created_at,
                        updated_at=time.time(),
                    )
                    prof.observations[feature_key] = promoted_obs
                    self.registry.register_or_update(prof)

            return PromotionEvaluationResult(
                feature_key=feature_key,
                current_tier=sample_obs.tier,
                target_tier=ObservationTier.PROMOTED_UNIVERSAL,
                qualified_apps_count=count,
                qualifying_apps=apps_tuple,
                is_promoted=True,
                rationale=f"Verified across {count} apps ({', '.join(apps_tuple)}). Elevated to universal discipline.",
            )

        return PromotionEvaluationResult(
            feature_key=feature_key,
            current_tier=sample_obs.tier,
            target_tier=ObservationTier.PER_APP_STABLE,
            qualified_apps_count=count,
            qualifying_apps=apps_tuple,
            is_promoted=False,
            rationale=f"Observed in only {count} app. At least 2 independent apps required for universal promotion.",
        )

    def render_profile_markdown(self, profile: AppOperatingProfile) -> str:
        """Render GitHub-style Markdown card displaying the application operating profile."""
        lines: list[str] = [
            f"### 🖥️ 应用专属动态操作档案: `{profile.display_name}` (`{profile.app_id}`)",
            f"- **Bundle ID**: `{profile.bundle_id or 'N/A'}`",
            f"- **可执行路径**: `{profile.executable_path or 'N/A'}`",
            f"- **特征规则数**: `{len(profile.observations)}`",
            "",
            "#### 📌 确定性技术特性 (Deterministic Quirks)",
        ]

        if profile.deterministic_features:
            for k, v in profile.deterministic_features.items():
                lines.append(f"- **`{k}`**: {v}")
        else:
            lines.append("- *(暂无底层确定性硬编码特征)*")

        lines.extend(["", "#### 🛡️ 经验观察与自愈进化记录 (Observations)"])

        active_count = 0
        falsified_count = 0
        for obs in profile.observations.values():
            if obs.status == FalsificationStatus.FALSIFIED:
                falsified_count += 1
                lines.append(f"- ~~`{obs.feature_key}`~~ [{obs.tier.value}]: {obs.statement} ❌ *(已证伪作废)*")
            else:
                active_count += 1
                icon = "🌐" if obs.tier == ObservationTier.PROMOTED_UNIVERSAL else "⚙️"
                lines.append(f"- {icon} **`{obs.feature_key}`** [{obs.tier.value}]: {obs.statement}")

        lines.append("")
        if falsified_count > 0:
            lines.extend(
                [
                    "> [!IMPORTANT]",
                    f"> 检测到 {falsified_count} 项历史经验已被实测证伪覆写。系统已自动纠偏，防止陈旧错误经验误导后续自动化分支。",
                ]
            )
        elif active_count > 0:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> 存在 {active_count} 条活跃技术规约，严格遵循易腐信息局部隔离与至少双应用升格原则。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!TIP]",
                    "> 当前档案暂无实测踩坑记录，遵循“教训能转代码绝不写文档”的工程原则。",
                ]
            )

        return "\n".join(lines)
