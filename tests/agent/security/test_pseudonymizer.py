"""Tests for PseudonymStore, pseudonymize_text, and PseudonymRestorer."""

from __future__ import annotations

import os
import threading
from collections.abc import Generator

import pytest

from myrm_agent_harness.agent.security.detection.pseudonym_store import (
    PseudonymStore,
    _stores,
    _stores_lock,
    get_pseudonym_store,
)
from myrm_agent_harness.agent.security.detection.pseudonymizer import (
    PseudonymizeResult,
    PseudonymRestorer,
    pseudonymize_text,
)
from myrm_agent_harness.agent.security.types import SensitivityLevel


@pytest.fixture()
def store(tmp_path: object) -> Generator[PseudonymStore]:
    db_path = os.path.join(str(tmp_path), "test_pseudonym.db")
    s = PseudonymStore(db_path)
    yield s
    s.close()


class TestPseudonymStore:
    def test_get_or_create_idempotent(self, store: PseudonymStore) -> None:
        p1 = store.get_or_create("张伟", "REAL_NAME", "s2")
        p2 = store.get_or_create("张伟", "REAL_NAME", "s2")
        assert p1 == p2
        assert p1 == "<REAL_NAME_1>"

    def test_different_types_independent_sequence(self, store: PseudonymStore) -> None:
        phone = store.get_or_create("13800138000", "PHONE_NUMBER", "s2")
        email = store.get_or_create("test@example.com", "EMAIL_ADDRESS", "s2")
        phone2 = store.get_or_create("13900139000", "PHONE_NUMBER", "s2")

        assert phone == "<PHONE_NUMBER_1>"
        assert email == "<EMAIL_ADDRESS_1>"
        assert phone2 == "<PHONE_NUMBER_2>"

    def test_resolve(self, store: PseudonymStore) -> None:
        store.get_or_create("张伟", "REAL_NAME", "s2")
        assert store.resolve("<REAL_NAME_1>") == "张伟"
        assert store.resolve("<UNKNOWN_1>") is None

    def test_resolve_all(self, store: PseudonymStore) -> None:
        store.get_or_create("张伟", "REAL_NAME", "s2")
        store.get_or_create("13800138000", "PHONE_NUMBER", "s2")

        text = "您好 <REAL_NAME_1>，您的手机号是 <PHONE_NUMBER_1>"
        restored = store.resolve_all(text)
        assert restored == "您好 张伟，您的手机号是 13800138000"

    def test_resolve_all_unknown_preserved(self, store: PseudonymStore) -> None:
        text = "Hello <UNKNOWN_TAG_99>, how are you?"
        assert store.resolve_all(text) == text

    def test_stats(self, store: PseudonymStore) -> None:
        store.get_or_create("a", "PHONE_NUMBER", "s2")
        store.get_or_create("b", "PHONE_NUMBER", "s2")
        store.get_or_create("c", "EMAIL_ADDRESS", "s2")
        stats = store.stats()
        assert stats["PHONE_NUMBER"] == 2
        assert stats["EMAIL_ADDRESS"] == 1


class TestPseudonymizeText:
    def test_basic_pseudonymization(self, store: PseudonymStore) -> None:
        content = "我叫张伟，手机 13800138000，邮箱 test@example.com"
        result = pseudonymize_text(content, store, SensitivityLevel.S2)
        assert isinstance(result, PseudonymizeResult)
        assert result.count >= 2
        assert "13800138000" not in result.text
        assert "test@example.com" not in result.text
        assert "<PHONE_NUMBER_" in result.text
        assert "<EMAIL_ADDRESS_" in result.text

    def test_empty_content(self, store: PseudonymStore) -> None:
        result = pseudonymize_text("", store, SensitivityLevel.S1)
        assert result.text == ""
        assert result.count == 0

    def test_no_pii_content(self, store: PseudonymStore) -> None:
        result = pseudonymize_text("Hello world, nice day!", store, SensitivityLevel.S2)
        assert result.count == 0
        assert result.text == "Hello world, nice day!"

    def test_idcard_pseudonymization(self, store: PseudonymStore) -> None:
        content = "身份证号码 110101199003074530"
        result = pseudonymize_text(content, store, SensitivityLevel.S3)
        assert result.count >= 1
        assert "<ID_CARD_" in result.text


class TestPseudonymRestorer:
    def test_complete_token_restoration(self, store: PseudonymStore) -> None:
        store.get_or_create("张伟", "REAL_NAME", "s2")
        restorer = PseudonymRestorer(store)

        result = restorer.process("Hello <REAL_NAME_1>, how are you?")
        assert result == "Hello 张伟, how are you?"

    def test_split_token_across_chunks(self, store: PseudonymStore) -> None:
        store.get_or_create("13800138000", "PHONE_NUMBER", "s2")
        restorer = PseudonymRestorer(store)

        part1 = restorer.process("Call me at <PHONE_")
        assert "<" not in part1
        assert part1 == "Call me at "

        part2 = restorer.process("NUMBER_1> please")
        assert part2 == "13800138000 please"

    def test_flush_remaining_buffer(self, store: PseudonymStore) -> None:
        store.get_or_create("test", "DATA", "s2")
        restorer = PseudonymRestorer(store)

        part1 = restorer.process("text <DA")
        assert part1 == "text "

        flushed = restorer.flush()
        assert flushed == "<DA"

    def test_no_buffer_flush_returns_empty(self, store: PseudonymStore) -> None:
        restorer = PseudonymRestorer(store)
        result = restorer.process("plain text no tokens")
        assert result == "plain text no tokens"
        assert restorer.flush() == ""

    def test_multiple_tokens_in_single_chunk(self, store: PseudonymStore) -> None:
        store.get_or_create("张伟", "REAL_NAME", "s2")
        store.get_or_create("13800138000", "PHONE_NUMBER", "s2")
        restorer = PseudonymRestorer(store)

        result = restorer.process("<REAL_NAME_1> phone: <PHONE_NUMBER_1>")
        assert result == "张伟 phone: 13800138000"

    def test_unknown_tokens_preserved(self, store: PseudonymStore) -> None:
        restorer = PseudonymRestorer(store)
        result = restorer.process("Unknown <FAKE_TAG_99> here")
        assert result == "Unknown <FAKE_TAG_99> here"

    def test_max_buffer_overflow(self, store: PseudonymStore) -> None:
        restorer = PseudonymRestorer(store)
        long_partial = "<" + "A" * 60
        result = restorer.process(long_partial)
        assert result == long_partial
        assert restorer._buffer == ""


class TestPseudonymStoreClose:
    def test_close_closes_connection(self, tmp_path: object) -> None:
        db_path = os.path.join(str(tmp_path), "close_test.db")
        s = PseudonymStore(db_path)
        s.get_or_create("test", "DATA", "s2")
        s.close()

    def test_get_or_create_thread_safety(self, store: PseudonymStore) -> None:
        results: list[str] = []
        errors: list[Exception] = []

        def worker(text: str) -> None:
            try:
                r = store.get_or_create(text, "PHONE_NUMBER", "s2")
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"phone_{i}",)) for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 10
        pseudonyms = set(results)
        assert len(pseudonyms) == 10


class TestGetPseudonymStoreFactory:
    def test_singleton_returns_same_instance(self, tmp_path: object) -> None:
        db_path = os.path.join(str(tmp_path), "factory_test.db")
        try:
            s1 = get_pseudonym_store(db_path)
            s2 = get_pseudonym_store(db_path)
            assert s1 is s2
        finally:
            with _stores_lock:
                removed = _stores.pop(db_path, None)
                if removed:
                    removed.close()

    def test_different_paths_return_different_instances(self, tmp_path: object) -> None:
        db1 = os.path.join(str(tmp_path), "factory_a.db")
        db2 = os.path.join(str(tmp_path), "factory_b.db")
        try:
            s1 = get_pseudonym_store(db1)
            s2 = get_pseudonym_store(db2)
            assert s1 is not s2
        finally:
            with _stores_lock:
                for p in (db1, db2):
                    removed = _stores.pop(p, None)
                    if removed:
                        removed.close()

    def test_creates_parent_directory(self, tmp_path: object) -> None:
        nested = os.path.join(str(tmp_path), "nested", "dir", "test.db")
        try:
            s = get_pseudonym_store(nested)
            assert os.path.isdir(os.path.dirname(nested))
            s.get_or_create("x", "DATA", "s2")
        finally:
            with _stores_lock:
                removed = _stores.pop(nested, None)
                if removed:
                    removed.close()


class TestPseudonymizeEdgeCases:
    def test_bank_card_luhn_validation(self, store: PseudonymStore) -> None:
        content = "Card: 6225882100000000"
        result = pseudonymize_text(content, store, SensitivityLevel.S3)
        assert isinstance(result, PseudonymizeResult)

    def test_password_context(self, store: PseudonymStore) -> None:
        content = "my password is abc123456"
        result = pseudonymize_text(content, store, SensitivityLevel.S3)
        if result.count > 0:
            assert "abc123456" not in result.text

    def test_multiple_same_pii(self, store: PseudonymStore) -> None:
        content = "Call 13800138000 or 13800138000 again"
        result = pseudonymize_text(content, store, SensitivityLevel.S2)
        assert result.count >= 1
        assert "13800138000" not in result.text
        assert "<PHONE_NUMBER_1>" in result.text

    def test_level_filtering_s3_only(self, store: PseudonymStore) -> None:
        """With level=S3, only S3 PII (ID card) is pseudonymized, S2 (phone) is untouched."""
        content = "Phone 13800138000, ID 110101199003074530"
        result = pseudonymize_text(content, store, SensitivityLevel.S3)
        assert "13800138000" in result.text
        assert "110101199003074530" not in result.text

    def test_level_filtering_s2_only(self, store: PseudonymStore) -> None:
        """With level=S2, only S2 PII (phone) is pseudonymized, S3 (ID card) is untouched."""
        content = "Phone 13800138000, ID 110101199003074530"
        result = pseudonymize_text(content, store, SensitivityLevel.S2)
        assert "13800138000" not in result.text
        assert "110101199003074530" in result.text

    def test_level_s1_returns_nothing(self, store: PseudonymStore) -> None:
        """S1 level has no patterns; nothing is pseudonymized."""
        content = "Phone 13800138000, ID 110101199003074530"
        result = pseudonymize_text(content, store, SensitivityLevel.S1)
        assert result.count == 0
        assert result.text == content
