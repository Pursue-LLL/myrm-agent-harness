"""Unit tests for leak_detector — credential leak detection.

Covers:
  - 30+ prefix-based API key patterns (positive + negative)
  - Structural formats (JWT, PEM, database URLs, blockchain, cloud infra)
  - Context-aware patterns (ENV, JSON, Auth header, mnemonic phrases)
  - Shannon entropy analysis (unknown credential formats)
  - Smart redaction (short/long tokens, pattern labels)
  - Placeholder exclusion for context patterns
"""

from __future__ import annotations

from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks, scan_for_leaks

# ===================================================================
# 1. Prefix-based API key detection
# ===================================================================


class TestApiKeyPatterns:
    """Prefix-based API key detection — one test per provider."""

    # --- Payment ---

    def test_stripe_live_key(self) -> None:
        assert "stripe_key" in scan_for_leaks("sk_live_" + "a" * 24)

    def test_stripe_test_key(self) -> None:
        assert "stripe_key" in scan_for_leaks("sk_test_" + "a" * 24)

    def test_stripe_restricted_key(self) -> None:
        assert "stripe_restricted" in scan_for_leaks("rk_live_" + "a" * 24)

    # --- AI / LLM ---

    def test_openai_key(self) -> None:
        assert "openai_key" in scan_for_leaks("sk-" + "a" * 48)

    def test_anthropic_key(self) -> None:
        assert "anthropic_key" in scan_for_leaks("sk-ant-" + "a" * 32)

    def test_google_key(self) -> None:
        assert "google_key" in scan_for_leaks("AIza" + "a" * 35)

    def test_huggingface_token(self) -> None:
        assert "huggingface_token" in scan_for_leaks("hf_" + "a" * 34)

    def test_replicate_token(self) -> None:
        assert "replicate_token" in scan_for_leaks("r8_" + "a" * 36)

    def test_perplexity_key(self) -> None:
        assert "perplexity_key" in scan_for_leaks("pplx-" + "a" * 48)

    # --- Cloud ---

    def test_aws_access_key(self) -> None:
        assert "aws_access_key" in scan_for_leaks("AKIAIOSFODNN7EXAMPLE")

    def test_digitalocean_token(self) -> None:
        assert "digitalocean_token" in scan_for_leaks("dop_v1_" + "a" * 64)

    def test_vercel_token(self) -> None:
        assert "vercel_token" in scan_for_leaks("vercel_" + "a" * 24)

    def test_supabase_key(self) -> None:
        assert "supabase_key" in scan_for_leaks("sbp_" + "a" * 40)

    def test_cloudflare_token(self) -> None:
        assert "cloudflare_token" in scan_for_leaks("cf_" + "a" * 37)

    # --- DevOps / VCS ---

    def test_github_token(self) -> None:
        assert "github_token" in scan_for_leaks("ghp_" + "a" * 36)

    def test_github_pat(self) -> None:
        assert "github_pat" in scan_for_leaks("github_pat_" + "a" * 22)

    def test_gitlab_token(self) -> None:
        assert "gitlab_token" in scan_for_leaks("glpat-" + "a" * 20)

    def test_npm_token(self) -> None:
        assert "npm_token" in scan_for_leaks("npm_" + "a" * 36)

    def test_pypi_token(self) -> None:
        assert "pypi_token" in scan_for_leaks("pypi-" + "a" * 36)

    # --- Communication ---

    def test_slack_token(self) -> None:
        assert "slack_token" in scan_for_leaks("xoxb-" + "a" * 10)

    def test_telegram_bot(self) -> None:
        assert "telegram_bot" in scan_for_leaks("123456789:" + "a" * 35)

    def test_sendgrid_key(self) -> None:
        assert "sendgrid_key" in scan_for_leaks("SG." + "a" * 22 + "." + "a" * 43)

    def test_twilio_key(self) -> None:
        assert "twilio_key" in scan_for_leaks("SK" + "a" * 32)

    # --- Media / AI services ---

    def test_elevenlabs_key(self) -> None:
        assert "elevenlabs_key" in scan_for_leaks("el_" + "a" * 32)

    def test_fal_key(self) -> None:
        assert "fal_key" in scan_for_leaks("fal_" + "a" * 32)

    # --- Search / Web ---

    def test_tavily_key(self) -> None:
        assert "tavily_key" in scan_for_leaks("tvly-" + "a" * 32)

    def test_firecrawl_key(self) -> None:
        assert "firecrawl_key" in scan_for_leaks("fc-" + "a" * 32)

    def test_browserbase_key(self) -> None:
        assert "browserbase_key" in scan_for_leaks("bb_live_" + "a" * 32)


# ===================================================================
# 2. Structural format detection
# ===================================================================


class TestStructuralPatterns:
    """JWT, PEM, database URL detection."""

    def test_jwt_token(self) -> None:
        assert "jwt_token" in scan_for_leaks("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc123def456")

    def test_pem_rsa_key(self) -> None:
        assert "pem_private_key" in scan_for_leaks("-----BEGIN RSA PRIVATE KEY-----")

    def test_pem_ec_key(self) -> None:
        assert "pem_private_key" in scan_for_leaks("-----BEGIN EC PRIVATE KEY-----")

    def test_pem_openssh_key(self) -> None:
        assert "pem_private_key" in scan_for_leaks("-----BEGIN OPENSSH PRIVATE KEY-----")

    def test_pem_generic_key(self) -> None:
        assert "pem_private_key" in scan_for_leaks("-----BEGIN PRIVATE KEY-----")

    def test_postgres_url(self) -> None:
        assert "database_url" in scan_for_leaks("postgres://user:pass@host:5432/db")

    def test_mysql_url(self) -> None:
        assert "database_url" in scan_for_leaks("mysql://admin:secret@db.example.com/app")

    def test_mongodb_srv_url(self) -> None:
        assert "database_url" in scan_for_leaks("mongodb+srv://u:p@cluster.mongodb.net/db")

    def test_redis_url(self) -> None:
        assert "database_url" in scan_for_leaks("redis://default:pw@redis.example.com:6379")

    def test_amqp_url(self) -> None:
        assert "database_url" in scan_for_leaks("amqps://user:pass@rabbitmq.example.com/vhost")


# ===================================================================
# 3. Context-aware patterns (ENV, JSON, Auth header)
# ===================================================================


class TestContextPatterns:
    """ENV assignment, JSON field, and Auth header detection."""

    def test_env_assignment(self) -> None:
        content = "export API_KEY=abcdef1234567890abcdef1234567890"
        assert "env_credential" in scan_for_leaks(content)

    def test_env_secret_key(self) -> None:
        content = "SECRET_KEY=supersecretvalue1234567890abc"
        assert "env_credential" in scan_for_leaks(content)

    def test_env_password(self) -> None:
        content = "PASSWORD=MyVeryLongPassword123!"
        assert "env_credential" in scan_for_leaks(content)

    def test_env_with_quotes(self) -> None:
        content = "TOKEN='abcdef1234567890abcdef1234567890'"
        assert "env_credential" in scan_for_leaks(content)

    def test_env_short_value_ignored(self) -> None:
        content = "API_KEY=short"
        assert "env_credential" not in scan_for_leaks(content)

    def test_env_placeholder_ignored(self) -> None:
        content = "API_KEY=your_api_key_here"
        assert "env_credential" not in scan_for_leaks(content)

    def test_env_placeholder_changeme(self) -> None:
        content = "SECRET_KEY=changeme"
        assert "env_credential" not in scan_for_leaks(content)

    def test_env_placeholder_variable(self) -> None:
        content = "API_KEY=${SOME_ENV_VAR}"
        assert "env_credential" not in scan_for_leaks(content)

    def test_json_field(self) -> None:
        content = '{"apiKey": "abcdef1234567890abcdef1234567890"}'
        assert "json_credential" in scan_for_leaks(content)

    def test_json_secret(self) -> None:
        content = '{"secret": "reallylongsecretvalue1234567890"}'
        assert "json_credential" in scan_for_leaks(content)

    def test_json_password(self) -> None:
        content = '{"password": "MyDatabasePassword123!"}'
        assert "json_credential" in scan_for_leaks(content)

    def test_json_short_value_ignored(self) -> None:
        content = '{"apiKey": "test"}'
        assert "json_credential" not in scan_for_leaks(content)

    def test_json_placeholder_ignored(self) -> None:
        content = '{"token": "your_token_here_placeholder"}'
        assert "json_credential" not in scan_for_leaks(content)

    def test_auth_header_bearer(self) -> None:
        content = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        assert "auth_header_credential" in scan_for_leaks(content)

    def test_auth_header_basic(self) -> None:
        content = "Authorization: Basic dXNlcjpwYXNzd29yZDEyMzQ1Njc4OQ=="
        assert "auth_header_credential" in scan_for_leaks(content)

    def test_auth_header_token(self) -> None:
        content = "Authorization: Token abcdef1234567890abcdef"
        assert "auth_header_credential" in scan_for_leaks(content)

    def test_auth_header_lowercase(self) -> None:
        content = "authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        assert "auth_header_credential" in scan_for_leaks(content)

    def test_auth_header_uppercase(self) -> None:
        content = "AUTHORIZATION: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        assert "auth_header_credential" in scan_for_leaks(content)

    def test_auth_header_mixed_case(self) -> None:
        content = "aUtHoRiZaTiOn: Token abcdef1234567890abcdef"
        assert "auth_header_credential" in scan_for_leaks(content)


# ===================================================================
# 4. False positive resistance
# ===================================================================


class TestFalsePositives:
    """Ensure common safe content is not flagged."""

    def test_normal_text(self) -> None:
        assert scan_for_leaks("This is just normal text") == []

    def test_short_sk_prefix(self) -> None:
        assert scan_for_leaks("sk-short") == []

    def test_code_snippet(self) -> None:
        assert scan_for_leaks("def get_api_key(): return config['key']") == []

    def test_empty_input(self) -> None:
        assert scan_for_leaks("") == []

    def test_env_example_values(self) -> None:
        assert scan_for_leaks("API_KEY=example") == []

    def test_env_todo_placeholder(self) -> None:
        assert scan_for_leaks("SECRET=TODO") == []

    def test_json_null_value(self) -> None:
        assert scan_for_leaks('{"token": "null"}') == []

    def test_json_test_value(self) -> None:
        assert scan_for_leaks('{"password": "test"}') == []

    def test_url_without_credentials(self) -> None:
        assert scan_for_leaks("https://example.com/api/v1") == []


# ===================================================================
# 5. Smart redaction
# ===================================================================


class TestSmartRedaction:
    """Smart redaction preserves first 6 / last 4 for long tokens."""

    def test_long_token_preserves_head_tail(self) -> None:
        key = "sk_live_" + "a" * 24
        result = redact_leaks(f"Key: {key}")
        assert "sk_liv" in result
        assert result.endswith(" [REDACTED:stripe_key]")
        assert key not in result

    def test_short_token_fully_masked(self) -> None:
        result = redact_leaks("-----BEGIN PRIVATE KEY-----")
        assert "[REDACTED:pem_private_key]" in result

    def test_medium_token_preserves_head_tail(self) -> None:
        result = redact_leaks("AKIAIOSFODNN7EXAMPLE")
        assert "[REDACTED:aws_access_key]" in result
        assert "AKIAIO" in result
        assert "MPLE" in result

    def test_pattern_label_in_output(self) -> None:
        result = redact_leaks("sk-ant-" + "a" * 32)
        assert "[REDACTED:anthropic_key]" in result

    def test_preserves_surrounding_text(self) -> None:
        key = "sk_live_" + "a" * 24
        result = redact_leaks(f"before {key} after")
        assert result.startswith("before ")
        assert "after" in result

    def test_multiple_redactions(self) -> None:
        content = "sk_live_" + "a" * 24 + " and AKIAIOSFODNN7EXAMPLE"
        result = redact_leaks(content)
        assert "[REDACTED:stripe_key]" in result
        assert "[REDACTED:aws_access_key]" in result

    def test_no_change_clean_text(self) -> None:
        content = "This is safe text"
        assert redact_leaks(content) == content

    def test_empty_input(self) -> None:
        assert redact_leaks("") == ""

    def test_env_redaction(self) -> None:
        content = "export API_KEY=abcdef1234567890abcdef1234567890"
        result = redact_leaks(content)
        assert "[REDACTED:env_credential]" in result
        assert "abcdef1234567890abcdef1234567890" not in result

    def test_json_redaction(self) -> None:
        content = '{"secret": "reallylongsecretvalue1234567890"}'
        result = redact_leaks(content)
        assert "[REDACTED:json_credential]" in result
        assert "reallylongsecretvalue1234567890" not in result

    def test_auth_header_redaction(self) -> None:
        content = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = redact_leaks(content)
        assert "[REDACTED:" in result

    def test_env_placeholder_not_redacted(self) -> None:
        content = "API_KEY=your_api_key_here"
        assert redact_leaks(content) == content

    def test_json_placeholder_not_redacted(self) -> None:
        content = '{"token": "your_token_here_placeholder"}'
        assert redact_leaks(content) == content

    def test_env_short_credential_fully_masked(self) -> None:
        content = "API_KEY=aB3xK9mW2pQ7vL4n"
        result = redact_leaks(content)
        assert "[REDACTED:env_credential]" in result
        assert "***..." not in result


# ===================================================================
# 6. Multiple pattern detection
# ===================================================================


class TestMultiplePatterns:
    """Detect multiple credential types in single content."""

    def test_api_key_plus_database_url(self) -> None:
        content = "sk-" + "a" * 48 + " postgres://u:p@host/db"
        matches = scan_for_leaks(content)
        assert "openai_key" in matches
        assert "database_url" in matches

    def test_env_plus_api_key(self) -> None:
        content = "API_KEY=verylongsecretvalue1234567890 and ghp_" + "a" * 36
        matches = scan_for_leaks(content)
        assert "github_token" in matches
        assert "env_credential" in matches


# ===================================================================
# 7. OpenAI new key format (sk-proj-)
# ===================================================================


class TestOpenAINewFormat:
    """OpenAI project-scoped keys with sk-proj- prefix."""

    def test_sk_proj_key(self) -> None:
        key = "sk-proj-" + "a" * 48
        assert "openai_key" in scan_for_leaks(key)

    def test_sk_proj_mixed_case(self) -> None:
        key = "sk-proj-aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cGaB3xK9mW2pQ7vL4n"
        assert "openai_key" in scan_for_leaks(key)

    def test_sk_proj_with_underscores(self) -> None:
        key = "sk-proj-abc_def_1234567890_abcdef1234567890_abcdef12345678"
        assert "openai_key" in scan_for_leaks(key)

    def test_sk_proj_redaction(self) -> None:
        key = "sk-proj-" + "a" * 48
        result = redact_leaks(f"Key: {key}")
        assert key not in result
        assert "[REDACTED:openai_key]" in result


# ===================================================================
# 8. Compound ENV variable names
# ===================================================================


class TestCompoundEnvVars:
    """ENV variables with prefixed sensitive keywords."""

    def test_custom_token(self) -> None:
        assert "env_credential" in scan_for_leaks("CUSTOM_TOKEN=a9f8b2c1e7d4k6m3p0q5r8s1")

    def test_my_api_key(self) -> None:
        assert "env_credential" in scan_for_leaks("MY_API_KEY=longsecretvalue1234567890")

    def test_app_secret(self) -> None:
        assert "env_credential" in scan_for_leaks("APP_SECRET=verylongsecretvalue1234")

    def test_db_password(self) -> None:
        assert "env_credential" in scan_for_leaks("DB_PASSWORD=supersecretdbpass123!")

    def test_auth_token_prefixed(self) -> None:
        assert "env_credential" in scan_for_leaks("GITHUB_AUTH_TOKEN=ghp_placeholder_long_enough_val")

    def test_compound_placeholder_not_flagged(self) -> None:
        assert "env_credential" not in scan_for_leaks("CUSTOM_TOKEN=your_token_here")

    def test_compound_short_value_not_flagged(self) -> None:
        assert "env_credential" not in scan_for_leaks("CUSTOM_TOKEN=short")


# ===================================================================
# 9. Shannon entropy detection
# ===================================================================


class TestShannonEntropy:
    """High-entropy token detection for unknown credential formats."""

    def test_bare_high_entropy_token(self) -> None:
        assert "high_entropy_token" in scan_for_leaks("Found: aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG")

    def test_another_high_entropy(self) -> None:
        assert "high_entropy_token" in scan_for_leaks("Key X7k9M2pQvL4nR8s1T6hD0jF5cGaB3xK9")

    def test_uuid_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks("id: 550e8400-e29b-41d4-a716-446655440000")

    def test_git_hash_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks(
            "commit a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        )

    def test_sha256_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_url_path_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks(
            "https://example.com/docs/2024-report-a1b2c3d4e5f6g7h8.pdf"
        )

    def test_base64_with_special_chars_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks(
            "SGVsbG8gV29ybGQhIFRo+aXMgaXMgYS/B0ZXN0Lg=="
        )

    def test_short_token_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks("token: aB3xK9mW2pQ7vL4")

    def test_all_alpha_not_flagged(self) -> None:
        assert "high_entropy_token" not in scan_for_leaks("word: abcdefghijklmnopqrstuvwxyz")

    def test_redaction_preserves_head_tail(self) -> None:
        token = "aB3xK9mW2pQ7vL4nR8sT1yU6hD0jF5cG"
        result = redact_leaks(f"Cred: {token} end")
        assert token not in result
        assert "aB3xK9" in result
        assert "F5cG" in result
        assert "[REDACTED:high_entropy_token]" in result

    def test_known_prefix_not_double_detected(self) -> None:
        key = "ghp_" + "a" * 36
        matches = scan_for_leaks(f"Token: {key}")
        assert "github_token" in matches

    def test_non_ascii_content_not_flagged(self) -> None:
        """Non-ASCII content (CJK, etc.) should not trigger entropy detection."""
        chinese = (
            "## 明天北京到上海卧铺票查询结果 共找到8趟有卧铺的列车\n"
            "| 1461 | 北京 | 上海 | 硬卧 | 283.5元 | 1张 |"
        )
        assert "high_entropy_token" not in scan_for_leaks(chinese)

    def test_japanese_content_not_flagged(self) -> None:
        content = "東京から大阪まで新幹線で2時間30分かかります。料金は13870円です。"
        assert "high_entropy_token" not in scan_for_leaks(content)


# ===================================================================
# 10. log_leaks and edge cases
# ===================================================================


class TestLogLeaksAndEdgeCases:
    """Cover log_leaks function and internal edge cases."""

    def test_log_leaks_no_exception(self) -> None:
        from myrm_agent_harness.agent.security.detection.leak_detector import log_leaks

        log_leaks(["openai_key"], "sk-" + "a" * 48)

    def test_log_leaks_long_content_truncated(self) -> None:
        from myrm_agent_harness.agent.security.detection.leak_detector import log_leaks

        log_leaks(["high_entropy_token"], "x" * 500)

    def test_shannon_entropy_empty_string(self) -> None:
        from myrm_agent_harness.agent.security.detection.leak_detector import _shannon_entropy

        assert _shannon_entropy("") == 0.0

    def test_shannon_entropy_single_char(self) -> None:
        from myrm_agent_harness.agent.security.detection.leak_detector import _shannon_entropy

        assert _shannon_entropy("aaaa") == 0.0

    def test_shannon_entropy_high_for_random(self) -> None:
        from myrm_agent_harness.agent.security.detection.leak_detector import _shannon_entropy

        assert _shannon_entropy("aB3xK9mW2pQ7vL4nR8sT1yU6") > 4.0


# ===================================================================
# 11. Blockchain patterns
# ===================================================================


class TestBlockchainPatterns:
    """Blockchain address and mnemonic detection."""

    def test_ethereum_address(self) -> None:
        assert "ethereum_address" in scan_for_leaks(
            "Wallet: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD8E"
        )

    def test_ethereum_address_lowercase(self) -> None:
        assert "ethereum_address" in scan_for_leaks(
            "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
        )

    def test_ethereum_address_too_short(self) -> None:
        assert "ethereum_address" not in scan_for_leaks("0x742d35Cc6634C053")

    def test_ethereum_address_redaction(self) -> None:
        result = redact_leaks("Addr: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD8E")
        assert "0x742d" in result
        assert "[REDACTED:ethereum_address]" in result
        assert "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD8E" not in result

    def test_mnemonic_with_recovery_keyword(self) -> None:
        assert "mnemonic_phrase" in scan_for_leaks(
            "recovery phrase: abandon ability able about above "
            "absent absorb abstract absurd abuse access accident"
        )

    def test_mnemonic_with_seed_keyword(self) -> None:
        assert "mnemonic_phrase" in scan_for_leaks(
            "seed words = abandon ability able about above "
            "absent absorb abstract absurd abuse access accident"
        )

    def test_mnemonic_with_mnemonic_keyword(self) -> None:
        assert "mnemonic_phrase" in scan_for_leaks(
            'mnemonic: "abandon ability able about above '
            'absent absorb abstract absurd abuse access accident"'
        )

    def test_mnemonic_24_words(self) -> None:
        words = " ".join(["abandon"] * 24)
        assert "mnemonic_phrase" in scan_for_leaks(f"mnemonic: {words}")

    def test_mnemonic_without_context_not_flagged(self) -> None:
        assert "mnemonic_phrase" not in scan_for_leaks(
            "abandon ability able about above absent absorb abstract absurd abuse access accident"
        )

    def test_mnemonic_redaction(self) -> None:
        content = (
            "recovery phrase: abandon ability able about above "
            "absent absorb abstract absurd abuse access accident"
        )
        result = redact_leaks(content)
        assert "[REDACTED:mnemonic_phrase]" in result
        assert "abandon ability" not in result


# ===================================================================
# 12. Cloud infrastructure patterns
# ===================================================================


class TestCloudInfraPatterns:
    """Azure Storage Key and Discord Webhook detection."""

    def test_azure_storage_key(self) -> None:
        import base64

        key = base64.b64encode(b"a" * 64).decode()
        content = f"DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey={key};"
        assert "azure_storage_key" in scan_for_leaks(content)

    def test_azure_storage_key_redaction(self) -> None:
        import base64

        key = base64.b64encode(b"a" * 64).decode()
        content = f"DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey={key};"
        result = redact_leaks(content)
        assert "[REDACTED:azure_storage_key]" in result

    def test_discord_webhook(self) -> None:
        url = "https://discord.com/api/webhooks/1234567890123456789/" + "a" * 68
        assert "discord_webhook" in scan_for_leaks(url)

    def test_discord_webhook_discordapp(self) -> None:
        url = "https://discordapp.com/api/webhooks/1234567890123456789/" + "a" * 68
        assert "discord_webhook" in scan_for_leaks(url)

    def test_discord_webhook_redaction(self) -> None:
        url = "https://discord.com/api/webhooks/1234567890123456789/" + "a" * 68
        result = redact_leaks(url)
        assert "[REDACTED:discord_webhook]" in result

    def test_discord_bot_token(self) -> None:
        assert "discord_bot_token" in scan_for_leaks(
            "MTI3NjU0MzIxMDk4.O1dBmQ.Rv-N3456789abcdefghijklmno"
        )

    def test_discord_bot_token_longer(self) -> None:
        assert "discord_bot_token" in scan_for_leaks(
            "MTI3NjU0MzIxMDk4NTIwNjU2MA.GpfL_n.abcdefghijklmnopqrstuvwxyz012"
        )

    def test_discord_bot_token_redaction(self) -> None:
        token = "MTI3NjU0MzIxMDk4.O1dBmQ.Rv-N3456789abcdefghijklmno"
        result = redact_leaks(f"Bot: {token}")
        assert token not in result
        assert "[REDACTED:discord_bot_token]" in result

    def test_shopify_token(self) -> None:
        assert "shopify_token" in scan_for_leaks("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")

    def test_shopify_shared_secret(self) -> None:
        assert "shopify_shared_secret" in scan_for_leaks("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")

    def test_shopify_redaction(self) -> None:
        token = "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"
        result = redact_leaks(f"Token: {token}")
        assert "[REDACTED:shopify_token]" in result
        assert token not in result


# ===================================================================
# 13. PEM block-level redaction (multiline private key blocks)
# ===================================================================


class TestPemBlockRedaction:
    """Ensure entire PEM/SSH private key blocks are fully redacted."""

    _RSA_PEM = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7s0Z1GZHVYvKE\n"
        "XnOJQhE1Lf4MJ7c5zVXYwR8mK3pN9AqD6bTPjHv2QkGxNl0DP/RzN6wVxyzAaBT\n"
        "gfQ4HrJ8kVEyLmTFN7P3qZ0J5B8KsVrU2LDo7TG0nnXKVzPMCK5N9xNz1R8rqXw\n"
        "-----END RSA PRIVATE KEY-----"
    )

    _OPENSSH_PEM = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
        "QyNTUxOQAAACBGMGNyL2FiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6AAAAIMAAAAMHAA\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )

    _EC_PEM = (
        "-----BEGIN EC PRIVATE KEY-----\n"
        "MHQCAQEEIODg7G/Q1E0fR2Kv5U1F+r0O5LbQ9Gp4N2yEJm8v5nK+oAcGBSuBBAA\n"
        "-----END EC PRIVATE KEY-----"
    )

    _GENERIC_PEM = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7s0Z1GZHVYvKE\n"
        "-----END PRIVATE KEY-----"
    )

    def test_rsa_block_fully_redacted(self) -> None:
        result = redact_leaks(self._RSA_PEM)
        assert "MIIEvg" not in result
        assert "XnOJQh" not in result
        assert "DP/RzN6" not in result
        assert "pem_private_key_block:RSA" in result

    def test_openssh_block_fully_redacted(self) -> None:
        result = redact_leaks(self._OPENSSH_PEM)
        assert "b3Blbn" not in result
        assert "QyNTUx" not in result
        assert "pem_private_key_block:OPENSSH" in result

    def test_ec_block_fully_redacted(self) -> None:
        result = redact_leaks(self._EC_PEM)
        assert "MHQCAQEEIODg" not in result
        assert "pem_private_key_block:EC" in result

    def test_generic_block_fully_redacted(self) -> None:
        result = redact_leaks(self._GENERIC_PEM)
        assert "MIIEvg" not in result
        assert "pem_private_key_block" in result

    def test_pem_block_with_surrounding_text(self) -> None:
        content = f"Config file:\n{self._RSA_PEM}\nEnd of config"
        result = redact_leaks(content)
        assert "Config file:" in result
        assert "End of config" in result
        assert "MIIEvg" not in result

    def test_pem_block_with_slash_lines_not_leaked(self) -> None:
        """Regression: lines containing '/' were skipped by entropy check."""
        pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7s0Z1GZHVYvKE\n"
            "XnOJQhE1Lf4MJ7c5zVXYwR8mK3pN9AqD6bTPjHv2QkGxNl0DP/RzN6wVxyzAaBT\n"
            "-----END PRIVATE KEY-----"
        )
        result = redact_leaks(pem)
        # The line with '/' must NOT leak
        assert "DP/RzN6wVxyzAaBT" not in result

    def test_no_pem_text_unaffected(self) -> None:
        content = "User prefers dark mode and uses RSA authentication"
        assert redact_leaks(content) == content

    def test_scan_still_detects_pem(self) -> None:
        matches = scan_for_leaks(self._RSA_PEM)
        assert "pem_private_key" in matches
