"""Unit tests for Client-Side PII Auto-Sanitization and Local Vault Reverse Mapping suite.

[POS]
Harness core security test suite verifying Chinese and international PII entity detection,
session-isolated local mapping vault, and bidirectional transparent pseudonymization.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.pii_vault import (
    LocalPiiMappingVault,
    PiiEntityDetector,
    PiiEntityType,
    PiiTransformer,
)


def test_pii_entity_detector_various_types() -> None:
    text = (
        "学员表：\n"
        "姓名：张三，学号：202100101，手机：13812345678。\n"
        "邮箱：zhangsan@university.edu.cn，身份证：110101199003072391，卡号：6222021234567890123。"
    )
    matches = PiiEntityDetector.detect_entities(text)
    assert len(matches) == 6

    detected_types = {m.entity_type for m in matches}
    assert PiiEntityType.CHINESE_NAME in detected_types
    assert PiiEntityType.STUDENT_ID in detected_types
    assert PiiEntityType.PHONE_NUMBER in detected_types
    assert PiiEntityType.EMAIL in detected_types
    assert PiiEntityType.ID_CARD in detected_types
    assert PiiEntityType.BANK_CARD in detected_types

    # Verify extracted raw values
    name_match = next(m for m in matches if m.entity_type == PiiEntityType.CHINESE_NAME)
    assert name_match.raw_value == "张三"

    phone_match = next(m for m in matches if m.entity_type == PiiEntityType.PHONE_NUMBER)
    assert phone_match.raw_value == "13812345678"


def test_local_pii_mapping_vault() -> None:
    vault = LocalPiiMappingVault()
    session_id = "sess_vault_01"

    vault.store_mapping(session_id, "[PERSON_1]", "李四")
    vault.store_mapping(session_id, "[PHONE_1]", "13900001111")

    assert vault.get_real_value(session_id, "[PERSON_1]") == "李四"
    assert vault.get_placeholder(session_id, "李四") == "[PERSON_1]"
    assert vault.get_real_value(session_id, "[UNKNOWN]") is None

    mappings = vault.list_mappings(session_id)
    assert len(mappings) == 2
    assert mappings["[PERSON_1]"] == "李四"

    # Clear session
    vault.clear_session(session_id)
    assert len(vault.list_mappings(session_id)) == 0


def test_pii_transformer_roundtrip_pseudonymization() -> None:
    vault = LocalPiiMappingVault()
    session_id = "sess_trans_01"

    original_text = (
        "提交名单：姓名：王五，联系手机：13799998888。\n"
        "后续请联系姓名：王五 核实。"
    )

    # 1. Outward pseudonymization
    san_res = PiiTransformer.pseudonymize(original_text, session_id, vault)
    assert san_res.placeholders_count >= 2
    assert "王五" not in san_res.sanitized_text
    assert "13799998888" not in san_res.sanitized_text
    assert "[CHINESE_NAME_" in san_res.sanitized_text
    assert "[PHONE_NUMBER_" in san_res.sanitized_text

    # Consistent placeholder check: repeated mention of '王五' must have the same placeholder
    name_placeholder = vault.get_placeholder(session_id, "王五")
    assert name_placeholder is not None
    assert san_res.sanitized_text.count(name_placeholder) == 2

    # 2. Inward desanitization (AI response simulation)
    ai_response = f"已核对 {name_placeholder} 的档案，联系电话已确认无误。"
    desan_res = PiiTransformer.desanitize(ai_response, session_id, vault)

    assert desan_res.restored_count == 1
    assert "王五" in desan_res.restored_text
    assert name_placeholder not in desan_res.restored_text
    assert desan_res.restored_text == "已核对 王五 的档案，联系电话已确认无误。"


def test_pii_transformer_empty_and_clean() -> None:
    vault = LocalPiiMappingVault()
    session_id = "sess_clean"

    # Empty text
    res_empty = PiiTransformer.pseudonymize("", session_id, vault)
    assert res_empty.sanitized_text == ""
    assert res_empty.placeholders_count == 0

    # Clean text without PII
    clean_text = "这是一份普通的学术论文草稿，不包含任何个人隐私信息。"
    res_clean = PiiTransformer.pseudonymize(clean_text, session_id, vault)
    assert res_clean.sanitized_text == clean_text
    assert res_clean.placeholders_count == 0

    res_restored = PiiTransformer.desanitize(clean_text, session_id, vault)
    assert res_restored.restored_text == clean_text
