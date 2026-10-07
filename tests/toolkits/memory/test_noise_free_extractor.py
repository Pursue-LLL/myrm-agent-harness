"""[POS]: tests/toolkits/memory/test_noise_free_extractor.py
[INPUT]: Mocked conversation turns, candidate facts with PII, and concurrent purge triggers.
[OUTPUT]: Comprehensive test assertions verifying noise stripping, PII interception, and epoch fencing.

Reference: Anthropic Commerce Agents (commerce_common/memory.py).
Tests tool stripping, PII regex gateway, and monotonic epoch fencing.
"""

from myrm_agent_harness.toolkits.memory.noise_free_extractor import (
    ConversationTurn,
    ExtractedFactCandidate,
    NoiseFreeAsyncMemoryExtractor,
    NoiseFreeConfig,
    PIISafetyGateway,
    PurgeGenerationEpochManager,
    ToolNoiseFilter,
)


def test_tool_noise_filter_strips_tool_and_system_noise() -> None:
    """Verify tool noise filter completely strips external tool receipts and XML blocks."""
    filter_engine = ToolNoiseFilter()

    turns: list[ConversationTurn] = [
        ConversationTurn(role="system", content="You are a helpful e-commerce agent."),
        ConversationTurn(role="user", content="我想找一双黑色慢跑鞋，42码。"),
        ConversationTurn(
            role="assistant",
            content='正在查询库存...\n```json\n{"sku": "SHOES-BLK-42", "price": 499, "stock": 12}\n```',
        ),
        ConversationTurn(
            role="tool",
            content='{"status": "success", "items": [{"id": "1001", "name": "CloudStrider 42"}]}',
            tool_call_id="call_search_998",
        ),
        ConversationTurn(
            role="assistant",
            content="为您推荐 CloudStrider 42 码，售价 499 元，目前库存充足。",
        ),
    ]

    cleaned_messages, tokens_saved = filter_engine.process_dialogue(turns)

    # System and tool turns are stripped
    roles = [m.role for m in cleaned_messages]
    assert roles == ["user", "assistant", "assistant"]
    assert "我想找一双黑色慢跑鞋" in cleaned_messages[0].clean_text
    assert "正在查询库存" in cleaned_messages[1].clean_text
    # Tool JSON block inside assistant turn was stripped
    assert "SHOES-BLK-42" not in cleaned_messages[1].clean_text
    assert "CloudStrider" in cleaned_messages[2].clean_text
    assert tokens_saved > 0

    transcript = filter_engine.render_clean_transcript(turns)
    assert "User: 我想找一双黑色慢跑鞋" in transcript
    assert "SHOES-BLK-42" not in transcript
    assert "status" not in transcript


def test_pii_safety_gateway_blocking_and_masking() -> None:
    """Verify code-level PII safety gateway catches credit cards, IBANs, and secret keys."""
    gateway = PIISafetyGateway()

    # Valid Visa card (Luhn compliant)
    cc_text = "用户的支付卡号是 4111 1111 1111 1111，请保存为默认卡。"
    res_cc = gateway.inspect(cc_text)
    assert not res_cc.is_clean
    assert any(v.rule_name == "credit_card" for v in res_cc.violations)

    # Valid IBAN pattern
    iban_text = "汇款至 DE89370400440532013000 德国商业银行。"
    res_iban = gateway.inspect(iban_text)
    assert not res_iban.is_clean
    assert any(v.rule_name == "iban" for v in res_iban.violations)

    # Secret API key
    key_text = "API Key 临时记为 sk-abcdef1234567890abcdef1234567890"
    res_key = gateway.inspect(key_text)
    assert not res_key.is_clean
    assert any(v.rule_name == "secret_token_key" for v in res_key.violations)

    # Safe text
    safe_text = "用户喜欢在周六上午九点跑步，偏好深色运动服。"
    res_safe = gateway.inspect(safe_text)
    assert res_safe.is_clean
    assert len(res_safe.violations) == 0

    # Masking mode
    mask_gateway = PIISafetyGateway(mask_instead_of_reject=True)
    masked_res = mask_gateway.inspect("测试密钥 sk-abcdef1234567890abcdef1234567890 存储")
    assert "[secret_token_key_REDACTED]" in masked_res.sanitized_text


def test_purge_generation_monotonic_epoch_fencing() -> None:
    """Verify monotonic purge generation epoch fencing stops ghost writes from resurrecting."""
    epoch_mgr = PurgeGenerationEpochManager()
    user_id = "user_alpha_42"

    assert epoch_mgr.get_generation(user_id) == 1

    # Task A starts, observing generation 1
    gen_a = epoch_mgr.start_extraction_task(user_id)
    assert gen_a == 1

    # User explicitly clicks Purge / Forget
    new_gen = epoch_mgr.bump_generation_on_purge(user_id)
    assert new_gen == 2
    assert epoch_mgr.get_generation(user_id) == 2

    # Task A finishes late and tries to write with observed generation 1
    allowed_a = epoch_mgr.validate_and_fence_write(user_id, observed_generation=gen_a)
    assert not allowed_a  # Must be dropped!

    # Task B starts under generation 2
    gen_b = epoch_mgr.start_extraction_task(user_id)
    assert gen_b == 2

    allowed_b = epoch_mgr.validate_and_fence_write(user_id, observed_generation=gen_b)
    assert allowed_b  # Must be allowed!

    status = epoch_mgr.get_status(user_id)
    assert status.current_generation == 2
    assert status.stale_writes_dropped == 1


def test_noise_free_extractor_end_to_end_orchestration() -> None:
    """Verify end-to-end extraction orchestrator with noise stripping, PII check, and epoch fence."""
    extractor = NoiseFreeAsyncMemoryExtractor(
        config=NoiseFreeConfig(strip_tool_receipts=True, enforce_pii_gate=True)
    )
    user_id = "user_beta_88"

    dialogue: list[ConversationTurn] = [
        ConversationTurn(role="user", content="我只喝燕麦奶拿铁，不要加糖。"),
        ConversationTurn(
            role="assistant",
            content="收到，已为您在星巴克下单大杯燕麦拿铁。",
            tool_calls=[{"name": "order_coffee", "args": '{"item": "oat_latte"}'}],
        ),
        ConversationTurn(
            role="tool",
            content='{"order_id": "ORD-1234", "status": "confirmed"}',
            tool_call_id="call_ord_1",
        ),
    ]

    # 1. Clean transcript preparation
    clean_text, observed_gen, tokens_saved = extractor.prepare_clean_context(user_id, dialogue)
    assert "我只喝燕麦奶拿铁" in clean_text
    assert "ORD-1234" not in clean_text
    assert observed_gen == 1
    assert tokens_saved >= 0

    # 2. Candidate containing PII is rejected
    pii_candidate = ExtractedFactCandidate(
        fact_id="fact_pii_01",
        fact_text="用户的支付卡是 4111-1111-1111-1111，请保存。",
        confidence=0.95,
        generation_observed=observed_gen,
    )
    admitted, reason, violation = extractor.commit_extracted_fact(user_id, pii_candidate)
    assert not admitted
    assert "PII safety gateway" in reason
    assert violation is not None

    # 3. Safe candidate is admitted
    safe_candidate = ExtractedFactCandidate(
        fact_id="fact_safe_01",
        fact_text="用户偏好燕麦奶拿铁，严格要求无糖配方。",
        confidence=0.92,
        generation_observed=observed_gen,
    )
    admitted_safe, reason_safe, _ = extractor.commit_extracted_fact(user_id, safe_candidate)
    assert admitted_safe
    assert "successfully validated" in reason_safe
    assert len(extractor.get_user_facts(user_id)) == 1

    # 4. User purges memory
    new_epoch = extractor.purge_user_memory(user_id)
    assert new_epoch == 2
    assert len(extractor.get_user_facts(user_id)) == 0

    # 5. Stale candidate with old generation 1 attempts write -> Fenced!
    stale_candidate = ExtractedFactCandidate(
        fact_id="fact_stale_02",
        fact_text="用户曾去过西雅图咖啡馆。",
        confidence=0.88,
        generation_observed=1,
    )
    admitted_stale, reason_stale, _ = extractor.commit_extracted_fact(user_id, stale_candidate)
    assert not admitted_stale
    assert "Stale generation write dropped" in reason_stale
    assert len(extractor.get_user_facts(user_id)) == 0

    status = extractor.get_epoch_status(user_id)
    assert status.current_generation == 2
    assert status.stale_writes_dropped == 1
    assert status.pii_violations_blocked == 1
