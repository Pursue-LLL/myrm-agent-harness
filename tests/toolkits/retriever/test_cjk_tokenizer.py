"""Tests for Deterministic CJK Bigram + Unigram Tokenizer."""

from __future__ import annotations

from myrm_agent_harness.api import (
    build_cjk_index_segment,
    build_cjk_query_token_tiers,
    build_cjk_query_tokens,
    tokenize_cjk_bigram,
)


def test_tokenize_cjk_pure_chinese() -> None:
    text = "沙箱部署"
    tokens = tokenize_cjk_bigram(text)
    # 单字 + 相邻二字，严格位置保序
    assert tokens == ["沙", "沙箱", "箱", "箱部", "部", "部署", "署"]


def test_tokenize_cjk_mixed_english_chinese_order_preserving() -> None:
    # "修复bug了" -> ASCII 单词不被前置，严格与原文相对位置一致
    text = "修复bug了"
    tokens = tokenize_cjk_bigram(text)
    assert tokens == ["修", "修复", "复", "bug", "了"]


def test_tokenize_cjk_technical_identifier_preserved() -> None:
    text = "部署k8s-prod集群"
    tokens = tokenize_cjk_bigram(text)
    assert "k8s-prod" in tokens
    assert "部署" in tokens
    assert "集群" in tokens


def test_build_cjk_index_segment_deduplication() -> None:
    text = "沙箱环境部署沙箱"
    seg = build_cjk_index_segment(text)
    # 验证去重并拼为空格分隔字符串
    token_list = seg.split(" ")
    assert len(token_list) == len(set(token_list))
    assert "沙箱" in token_list
    assert "部署" in token_list


def test_build_cjk_query_token_tiers_strict_and_relaxed() -> None:
    query = "部署沙箱"
    tiers = build_cjk_query_token_tiers(query)
    assert len(tiers) == 2
    strict, relaxed = tiers[0], tiers[1]

    # strict 包含 unigram + bigram
    assert "部署" in strict
    assert "沙箱" in strict
    assert "部" in strict
    assert "署" in strict
    assert "沙" in strict
    assert "箱" in strict

    # relaxed 过滤掉 CJK bigram，只留 unigrams 与 ASCII
    assert "部" in relaxed
    assert "署" in relaxed
    assert "沙" in relaxed
    assert "箱" in relaxed
    assert "部署" not in relaxed
    assert "沙箱" not in relaxed
    assert "署沙" not in relaxed


def test_build_cjk_query_token_tiers_pure_ascii_single_tier() -> None:
    query = "kubernetes pod restart"
    tiers = build_cjk_query_token_tiers(query)
    # 纯 ASCII 不需要放宽档，只返回 [strict]
    assert len(tiers) == 1
    assert tiers[0] == ["kubernetes", "pod", "restart"]


def test_build_cjk_query_tokens() -> None:
    tokens = build_cjk_query_tokens("部署沙箱")
    assert "部署" in tokens
    assert "沙箱" in tokens


def test_tokenize_empty_and_punctuation() -> None:
    assert tokenize_cjk_bigram("") == []
    assert tokenize_cjk_bigram("   \n\t  ") == []
    assert tokenize_cjk_bigram("，。！？；：") == []
    assert build_cjk_index_segment("") == ""
    assert build_cjk_query_token_tiers("") == []
