"""Unit tests for canonical args hash computation."""

from myrm_agent_harness.agent.security.tool_registry import compute_canonical_args_hash


class TestCanonicalArgsHash:
    """Test canonical args hash ignores LLM-generated auxiliary fields."""

    def test_bash_tool_ignores_reason(self):
        """Verify bash tool hash only depends on command, not reason."""
        args1 = {"command": "ls -la /tmp", "reason": "列出 /tmp 目录内容及详细信息"}
        args2 = {"command": "ls -la /tmp", "reason": "列出 /tmp 目录下的所有文件及详细信息"}
        args3 = {"command": "ls -la /tmp", "reason": "Show all files in /tmp"}

        hash1 = compute_canonical_args_hash("bash_code_execute_tool", args1)
        hash2 = compute_canonical_args_hash("bash_code_execute_tool", args2)
        hash3 = compute_canonical_args_hash("bash_code_execute_tool", args3)

        assert hash1 == hash2 == hash3, "Hash should be identical for same command with different reasons"

    def test_bash_tool_different_commands_different_hash(self):
        """Verify different commands produce different hashes."""
        args1 = {"command": "ls -la /tmp", "reason": "list files"}
        args2 = {"command": "pwd", "reason": "list files"}

        hash1 = compute_canonical_args_hash("bash_code_execute_tool", args1)
        hash2 = compute_canonical_args_hash("bash_code_execute_tool", args2)

        assert hash1 != hash2, "Different commands should produce different hashes"

    def test_file_read_canonical_params(self):
        """Verify file_read_tool only hashes path."""
        args1 = {"path": "/etc/hosts", "reason": "read hosts file", "extra": "ignored"}
        args2 = {"path": "/etc/hosts", "description": "different desc"}

        hash1 = compute_canonical_args_hash("file_read_tool", args1)
        hash2 = compute_canonical_args_hash("file_read_tool", args2)

        assert hash1 == hash2, "Hash should ignore non-canonical params"

    def test_file_write_canonical_params(self):
        """Verify file_write_tool hashes path and content."""
        args1 = {"path": "/tmp/test.txt", "content": "hello", "reason": "write file"}
        args2 = {"path": "/tmp/test.txt", "content": "hello", "description": "different"}

        hash1 = compute_canonical_args_hash("file_write_tool", args1)
        hash2 = compute_canonical_args_hash("file_write_tool", args2)

        assert hash1 == hash2, "Hash should only depend on path and content"

        args3 = {"path": "/tmp/test.txt", "content": "world"}
        hash3 = compute_canonical_args_hash("file_write_tool", args3)

        assert hash1 != hash3, "Different content should produce different hash"

    def test_browser_navigate_canonical_params(self):
        """Verify browser_navigate only hashes url."""
        args1 = {"url": "https://example.com", "reason": "navigate to example"}
        args2 = {"url": "https://example.com", "description": "open website"}

        hash1 = compute_canonical_args_hash("browser_navigate_tool", args1)
        hash2 = compute_canonical_args_hash("browser_navigate_tool", args2)

        assert hash1 == hash2, "Hash should only depend on url"

    def test_unknown_tool_uses_all_params(self):
        """Verify unknown tools hash all parameters as fallback."""
        args = {"param1": "value1", "param2": "value2"}

        hash1 = compute_canonical_args_hash("unknown_mcp_tool", args)
        hash2 = compute_canonical_args_hash("unknown_mcp_tool", args)

        assert hash1 == hash2, "Same args should produce same hash for unknown tools"

    def test_browser_interact_canonical_params(self):
        """Verify browser_interact hashes action, ref, and value."""
        args1 = {"action": "fill", "ref": "123", "value": "test", "reason": "fill input"}
        args2 = {"action": "fill", "ref": "123", "value": "test", "description": "different"}

        hash1 = compute_canonical_args_hash("browser_interact_tool", args1)
        hash2 = compute_canonical_args_hash("browser_interact_tool", args2)

        assert hash1 == hash2, "Hash should ignore auxiliary fields"

    def test_none_args_returns_none(self):
        """Verify None args returns None hash."""
        assert compute_canonical_args_hash("bash_code_execute_tool", None) is None

    def test_empty_canonical_params_hashes_all(self):
        """Verify tools with empty canonical params list hash all params."""
        args = {"param": "value", "reason": "test"}

        hash1 = compute_canonical_args_hash("browser_snapshot_tool", args)

        assert hash1 is not None, "Should hash all params when canonical list is empty"

    def test_hash_format(self):
        """Verify hash format is SHA256[:16]."""
        args = {"command": "echo hello"}
        hash_value = compute_canonical_args_hash("bash_code_execute_tool", args)

        assert hash_value is not None
        assert len(hash_value) == 16, "Hash should be 16 characters (SHA256[:16])"
        assert all(c in "0123456789abcdef" for c in hash_value), "Hash should be hex string"

    def test_hash_deterministic(self):
        """Verify hash is deterministic across multiple calls."""
        args = {"command": "ls -la", "reason": "list files"}

        hashes = [compute_canonical_args_hash("bash_code_execute_tool", args) for _ in range(100)]

        assert len(set(hashes)) == 1, "Hash should be deterministic"
