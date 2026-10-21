"""Unit tests for the Feature Flags system."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.features import (
    _reset_for_testing,
    get_features,
    init_features,
    is_initialized,
    registry,
)
from myrm_agent_harness.core.features.types import (
    DeprecationInfo,
    ExperimentalInfo,
    FeatureSpec,
    FeatureStage,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset global state before each test."""
    _reset_for_testing()
    yield
    _reset_for_testing()


# ──────────────────────────────────────────────
# FeatureSpec validation
# ──────────────────────────────────────────────


class TestFeatureSpec:
    def test_valid_stable_feature(self):
        spec = FeatureSpec(
            id="shell_tool",
            key="shell_tool",
            stage=FeatureStage.STABLE,
            default_enabled=True,
            description="Shell tool",
        )
        assert spec.id == "shell_tool"
        assert spec.default_enabled is True

    def test_valid_experimental_feature(self):
        spec = FeatureSpec(
            id="deep_research",
            key="deep_research",
            stage=FeatureStage.EXPERIMENTAL,
            default_enabled=False,
            description="Deep research",
            experimental_info=ExperimentalInfo(
                name="Deep Research",
                description="Multi-step research",
                announcement="NEW!",
            ),
        )
        assert spec.experimental_info is not None
        assert spec.experimental_info.name == "Deep Research"

    def test_experimental_without_info_raises(self):
        with pytest.raises(ValueError, match="missing experimental_info"):
            FeatureSpec(
                id="bad",
                key="bad",
                stage=FeatureStage.EXPERIMENTAL,
                default_enabled=False,
                description="Bad",
            )

    def test_deprecated_without_info_raises(self):
        with pytest.raises(ValueError, match="missing deprecation_info"):
            FeatureSpec(
                id="old",
                key="old",
                stage=FeatureStage.DEPRECATED,
                default_enabled=False,
                description="Old",
            )

    def test_valid_deprecated_feature(self):
        spec = FeatureSpec(
            id="old_search",
            key="old_search",
            stage=FeatureStage.DEPRECATED,
            default_enabled=False,
            description="Old search",
            deprecation_info=DeprecationInfo(
                migration_hint="Use web_search instead",
            ),
        )
        assert spec.deprecation_info is not None

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must not be empty"):
            FeatureSpec(id="", key="k", stage=FeatureStage.STABLE, default_enabled=True, description="x")

    def test_self_dependency_raises(self):
        with pytest.raises(ValueError, match="cannot depend on itself"):
            FeatureSpec(
                id="a",
                key="a",
                stage=FeatureStage.STABLE,
                default_enabled=True,
                description="x",
                depends_on=frozenset({"a"}),
            )


# ──────────────────────────────────────────────
# FeatureStage properties
# ──────────────────────────────────────────────


class TestFeatureStage:
    def test_visibility(self):
        assert not FeatureStage.UNDER_DEVELOPMENT.is_visible_to_users
        assert FeatureStage.EXPERIMENTAL.is_visible_to_users
        assert FeatureStage.STABLE.is_visible_to_users
        assert FeatureStage.DEPRECATED.is_visible_to_users
        assert not FeatureStage.REMOVED.is_visible_to_users

    def test_active(self):
        assert FeatureStage.STABLE.is_active
        assert FeatureStage.EXPERIMENTAL.is_active
        assert not FeatureStage.REMOVED.is_active


# ──────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────


def _stable_spec(id_: str, default: bool = True) -> FeatureSpec:
    return FeatureSpec(id=id_, key=id_, stage=FeatureStage.STABLE, default_enabled=default, description=id_)


class TestRegistry:
    def test_register_and_get(self):
        spec = _stable_spec("foo")
        registry.register(spec)
        assert registry.get("foo") == spec

    def test_get_by_key(self):
        spec = FeatureSpec(
            id="my_feature",
            key="my_feature_key",
            stage=FeatureStage.STABLE,
            default_enabled=True,
            description="test",
        )
        registry.register(spec)
        assert registry.get_by_key("my_feature_key") == spec

    def test_duplicate_same_spec_ok(self):
        spec = _stable_spec("dup")
        registry.register(spec)
        registry.register(spec)
        assert registry.get("dup") == spec

    def test_duplicate_different_spec_raises(self):
        registry.register(_stable_spec("dup2", default=True))
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_stable_spec("dup2", default=False))

    def test_duplicate_key_raises(self):
        registry.register(
            FeatureSpec(id="a", key="shared_key", stage=FeatureStage.STABLE, default_enabled=True, description="a")
        )
        with pytest.raises(ValueError, match="already used by"):
            registry.register(
                FeatureSpec(id="b", key="shared_key", stage=FeatureStage.STABLE, default_enabled=True, description="b")
            )

    def test_all_specs_sorted(self):
        registry.register(_stable_spec("zzz"))
        registry.register(_stable_spec("aaa"))
        specs = registry.all_specs()
        assert [s.id for s in specs] == ["aaa", "zzz"]

    def test_experimental_filter(self):
        registry.register(_stable_spec("stable"))
        registry.register(
            FeatureSpec(
                id="exp",
                key="exp",
                stage=FeatureStage.EXPERIMENTAL,
                default_enabled=False,
                description="exp",
                experimental_info=ExperimentalInfo(name="Exp", description="desc"),
            )
        )
        assert len(registry.experimental_specs()) == 1
        assert registry.experimental_specs()[0].id == "exp"

    def test_is_known_key(self):
        registry.register(_stable_spec("known"))
        assert registry.is_known_key("known")
        assert not registry.is_known_key("unknown")


# ──────────────────────────────────────────────
# FeatureSet
# ──────────────────────────────────────────────


class TestFeatureSet:
    def test_defaults_from_spec(self):
        registry.register(_stable_spec("on", default=True))
        registry.register(_stable_spec("off", default=False))
        fs = init_features()
        assert fs.enabled("on")
        assert not fs.enabled("off")

    def test_overrides_take_precedence(self):
        registry.register(_stable_spec("feat", default=False))
        fs = init_features(overrides={"feat": True})
        assert fs.enabled("feat")

    def test_defaults_layer(self):
        registry.register(_stable_spec("feat", default=True))
        fs = init_features(defaults={"feat": False})
        assert not fs.enabled("feat")

    def test_overrides_over_defaults(self):
        registry.register(_stable_spec("feat", default=True))
        fs = init_features(defaults={"feat": False}, overrides={"feat": True})
        assert fs.enabled("feat")

    def test_removed_features_excluded(self):
        registry.register(
            FeatureSpec(
                id="gone",
                key="gone",
                stage=FeatureStage.REMOVED,
                default_enabled=True,
                description="gone",
            )
        )
        fs = init_features()
        assert not fs.enabled("gone")

    def test_removed_override_warns(self):
        registry.register(
            FeatureSpec(
                id="gone",
                key="gone",
                stage=FeatureStage.REMOVED,
                default_enabled=False,
                description="gone",
            )
        )
        fs = init_features(overrides={"gone": True})
        assert not fs.enabled("gone")
        assert any("removed" in w for w in fs.warnings())

    def test_unknown_key_warns(self):
        fs = init_features(overrides={"nonexistent": True})
        assert any("Unknown" in w for w in fs.warnings())

    def test_dependency_normalization(self):
        registry.register(_stable_spec("base", default=False))
        registry.register(
            FeatureSpec(
                id="child",
                key="child",
                stage=FeatureStage.STABLE,
                default_enabled=False,
                description="child",
                depends_on=frozenset({"base"}),
            )
        )
        fs = init_features(overrides={"child": True})
        assert fs.enabled("child")
        assert fs.enabled("base")

    def test_enable_disable_runtime(self):
        registry.register(_stable_spec("toggle", default=False))
        fs = init_features()
        assert not fs.enabled("toggle")
        fs.enable("toggle")
        assert fs.enabled("toggle")
        fs.disable("toggle")
        assert not fs.enabled("toggle")

    def test_enable_unknown_raises(self):
        fs = init_features()
        with pytest.raises(ValueError, match="Unknown feature"):
            fs.enable("nonexistent")

    def test_enabled_non_default(self):
        registry.register(_stable_spec("a", default=True))
        registry.register(_stable_spec("b", default=False))
        fs = init_features(overrides={"a": False, "b": True})
        non_defaults = fs.enabled_non_default()
        assert ("a", False) in non_defaults
        assert ("b", True) in non_defaults

    def test_to_dict(self):
        registry.register(_stable_spec("x", default=True))
        registry.register(_stable_spec("y", default=False))
        fs = init_features()
        d = fs.to_dict()
        assert d["x"] is True
        assert d["y"] is False

    def test_unstable_warning(self):
        registry.register(
            FeatureSpec(
                id="dev",
                key="dev",
                stage=FeatureStage.UNDER_DEVELOPMENT,
                default_enabled=False,
                description="dev",
            )
        )
        fs = init_features(overrides={"dev": True})
        assert any("under development" in w for w in fs.warnings())

    def test_deprecated_warning(self):
        registry.register(
            FeatureSpec(
                id="old",
                key="old",
                stage=FeatureStage.DEPRECATED,
                default_enabled=False,
                description="old",
                deprecation_info=DeprecationInfo(migration_hint="Use new_thing"),
            )
        )
        fs = init_features(overrides={"old": True})
        assert any("deprecated" in w for w in fs.warnings())


# ──────────────────────────────────────────────
# Global accessors
# ──────────────────────────────────────────────


class TestGlobalAccessors:
    def test_not_initialized_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_features()

    def test_is_initialized(self):
        assert not is_initialized()
        init_features()
        assert is_initialized()

    def test_get_features_returns_same(self):
        registry.register(_stable_spec("s"))
        fs = init_features()
        assert get_features() is fs
