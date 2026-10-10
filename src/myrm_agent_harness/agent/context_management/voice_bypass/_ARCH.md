# voice_bypass/

## Overview
Voice command local bypass and tiered intent routing subsystem. Provides deterministic Tier-0 resolution for high-frequency control, navigation, and view commands (<50ms latency, zero model tokens, 100% offline capable) and transparent fallback to Tier-1 Agent LLM execution for complex task semantics.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports all types, matcher, and unified facade suite. | ✅ |
| `voice_bypass_types.py` | Types | VoiceIntentTier, VoiceActionCategory, VoiceBypassAction, and MatchResult schemas. | ✅ |
| `voice_command_matcher.py` | Matcher | Deterministic regex compiler and colloquial utterance normalizer. | ✅ |
| `voice_command_bypass_suite.py` | Facade | Unified suite facade for single/batch utterance routing and token savings telemetry. | ✅ |

## Key Dependencies

- `re`, `time`, `logging`, `dataclasses`, `enum`
- Pure stdlib, zero heavyweight third-party dependencies

## Key Design Decisions

- **Deterministic Tier-0 Matching**: Common voice commands ("停止", "暂停", "新建会话", "重试", "导出对话") match compiled regexes instantly (<5ms), avoiding expensive STT -> LLM network roundtrips.
- **Colloquial Normalization**: Automatically strips natural conversational prefixes ("请", "帮我", "please", "hey myrm") and trailing speech punctuation before pattern evaluation.
- **Complexity Guard**: Utterances longer than 30 characters or containing question/reasoning words ("为什么", "怎么", "explain") bypass local rules directly to Tier-1 Agent LLM to avoid false positive truncation.
- **Token Savings Ledger**: Every Tier-0 matched action credits a default ~450 tokens saved estimate, feeding telemetry and cost metrics.
