from myrm_agent_harness.toolkits.code_execution.executors.models import scrub_sensitive_info


def test_scrub_absolute_paths():
    """Absolute paths are replaced with static placeholders."""
    text = "The log file is at /Users/yululiu/project/logs/test.log"
    expected = "The log file is at <HOME>/project/logs/test.log"
    assert scrub_sensitive_info(text) == expected

    text_esc = "Path: \\/Users\\/yululiu\\/test.py"
    expected_esc = "Path: <HOME>\\/test.py"
    assert scrub_sensitive_info(text_esc) == expected_esc


def test_scrub_credentials():
    """API keys and tokens are masked by the redact engine."""
    text = "Found sk-1234567890abcdef in config"
    scrubbed = scrub_sensitive_info(text)
    assert "sk-1234567890abcdef" not in scrubbed
    assert "***" in scrubbed or "..." in scrubbed

    text_bearer = "Authorization: Bearer my-secret-token-long-enough"
    res = scrub_sensitive_info(text_bearer)
    assert "my-secret-token-long-enough" not in res

    text_ghp = "Token: ghp_1234567890abcdef1234"
    res_ghp = scrub_sensitive_info(text_ghp)
    assert "ghp_1234567890abcdef1234" not in res_ghp


def test_scrub_mixed_content():
    """Mixed paths + credentials are both scrubbed."""
    text = "User /Users/yululiu accessed /tmp/data with API_KEY=mysecretvalue123"
    res = scrub_sensitive_info(text)
    assert "<HOME>" in res
    assert "<ABS_PATH>" in res
    assert "mysecretvalue123" not in res


def test_scrub_empty_and_none():
    """Empty/falsy inputs pass through unchanged."""
    assert scrub_sensitive_info("") == ""
    assert scrub_sensitive_info(None) is None  # type: ignore[arg-type]


def test_scrub_cli_flag_equals():
    """CLI `--flag=value` secrets are masked by the redact engine."""
    text = "Deploying with --api-key=sk-abcdefghijklmnop1234 --region=us"
    scrubbed = scrub_sensitive_info(text)
    assert "sk-abcdefghijklmnop1234" not in scrubbed
    assert "sk-abc" in scrubbed
    assert "--region=us" in scrubbed


def test_scrub_dotted_env_key():
    """Dotted config keys like `app.api.key=` are masked."""
    text = "spring.datasource.password=hunter2hunter2hunter2"
    scrubbed = scrub_sensitive_info(text)
    assert "hunter2hunter2hunter2" not in scrubbed
    assert "hunter" in scrubbed or "***" in scrubbed


def test_scrub_large_text_no_duplicate_mask():
    """Secrets in large text are masked exactly once (no duplicated output)."""
    text = "TOKEN=sk-abcdefghijklmnop1234" + "a" * 32768
    scrubbed = scrub_sensitive_info(text)
    assert scrubbed.count("sk-abc") == 1
    assert scrubbed.count("...") == 1


def test_scrub_no_sensitive_content():
    """Plain text without sensitive content is unchanged."""
    text = "Hello world, this is a test."
    assert scrub_sensitive_info(text) == text
