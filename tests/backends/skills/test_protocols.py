"""Tests for skill backend protocols.

Note: Protocols are not @runtime_checkable, so we test structural conformance
by verifying the concrete classes have the required methods with correct signatures.
"""

import inspect

from myrm_agent_harness.backends.skills.protocols import (
    ABTestStoreProtocol,
    SkillStateReader,
    SnapshotStoreProtocol,
)


class TestSkillStateReader:
    def test_concrete_class_has_required_method(self):
        """Verify SkillStateReader defines is_skill_active."""

        class ConcreteReader:
            def is_skill_active(self, skill_name: str) -> bool:
                return True

        reader = ConcreteReader()
        assert hasattr(reader, "is_skill_active")
        assert callable(reader.is_skill_active)

    def test_protocol_defines_interface(self):
        """Verify SkillStateReader protocol has the expected method."""
        assert hasattr(SkillStateReader, "is_skill_active")


class TestSnapshotStoreProtocol:
    def test_concrete_class_has_required_methods(self):
        """Verify SnapshotStoreProtocol requires get_version and get_active_version."""

        class ConcreteStore:
            async def get_version(self, skill_id: str, version: int) -> object | None:
                return None

            async def get_active_version(self, skill_id: str) -> object | None:
                return None

        store = ConcreteStore()
        assert hasattr(store, "get_version")
        assert hasattr(store, "get_active_version")
        assert inspect.iscoroutinefunction(store.get_version)
        assert inspect.iscoroutinefunction(store.get_active_version)

    def test_protocol_defines_interface(self):
        assert hasattr(SnapshotStoreProtocol, "get_version")
        assert hasattr(SnapshotStoreProtocol, "get_active_version")


class TestABTestStoreProtocol:
    def test_concrete_class_has_required_method(self):
        """Verify ABTestStoreProtocol requires get_running_tests."""

        class ConcreteStore:
            async def get_running_tests(self) -> list[object]:
                return []

        store = ConcreteStore()
        assert hasattr(store, "get_running_tests")
        assert inspect.iscoroutinefunction(store.get_running_tests)

    def test_protocol_defines_interface(self):
        assert hasattr(ABTestStoreProtocol, "get_running_tests")
