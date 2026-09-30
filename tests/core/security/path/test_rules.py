"""Protected-path policy — sensitive, instruction and evidence path rules.

Mirrors `core.security.path.rules`.
"""


from myrm_agent_harness.core.security.path import (
    SENSITIVE_FILE_PATTERNS,
    is_evidence_readonly_file,
    is_sensitive_file,
)


class TestIsSensitiveFile:
    """Test is_sensitive_file() function."""

    def test_ssh_keys(self) -> None:
        assert is_sensitive_file("/home/user/.ssh/id_rsa") is True
        assert is_sensitive_file("id_ed25519") is True

    def test_pem_key_files(self) -> None:
        assert is_sensitive_file("server.pem") is True
        assert is_sensitive_file("/path/to/cert.key") is True
        assert is_sensitive_file("bundle.p12") is True

    def test_env_files(self) -> None:
        assert is_sensitive_file(".env") is True
        assert is_sensitive_file(".env.local") is True
        assert is_sensitive_file("/project/.env.production") is True

    def test_credential_files(self) -> None:
        assert is_sensitive_file("credentials.json") is True
        assert is_sensitive_file("secrets.json") is True

    def test_database_files(self) -> None:
        assert is_sensitive_file("data.db") is True
        assert is_sensitive_file("app.sqlite3") is True

    def test_password_files(self) -> None:
        assert is_sensitive_file("passwd") is True
        assert is_sensitive_file("shadow") is True

    def test_safe_files(self) -> None:
        assert is_sensitive_file("main.py") is False
        assert is_sensitive_file("README.md") is False
        assert is_sensitive_file("package.json") is False

    def test_aws_credentials(self) -> None:
        assert is_sensitive_file("/home/user/.aws/credentials") is True

    def test_git_config(self) -> None:
        assert is_sensitive_file("/project/.git/config") is True

    def test_case_variants_are_still_sensitive(self) -> None:
        for path in ("KEY.PEM", ".ENV", ".Env", "CREDENTIALS.JSON", "ID_RSA", "APP.DB", "PASSWD", "SHADOW"):
            assert is_sensitive_file(path) is True, path

    def test_case_variants_in_nested_directories(self) -> None:
        assert is_sensitive_file("/home/user/.AWS/Credentials") is True
        assert is_sensitive_file("/project/.GIT/Config") is True

class TestIsEvidenceReadonlyFile:
    """Verify the evidence guard cannot be side-stepped by respelling a directory."""

    def test_lowercase_directories(self) -> None:
        assert is_evidence_readonly_file("evidence/chart.png") is True
        assert is_evidence_readonly_file("user_inputs/notes.pdf") is True

    def test_case_variants_are_still_readonly(self) -> None:
        for path in ("EVIDENCE/chart.png", "Evidence/chart.png", "USER_INPUTS/notes.pdf"):
            assert is_evidence_readonly_file(path) is True, path

    def test_unrelated_paths_are_writable(self) -> None:
        assert is_evidence_readonly_file("outputs/chart.png") is False

    def test_bare_directory_forms_are_readonly(self) -> None:
        """A whole protected directory is protected, not only its contents.

        ``rm -rf evidence`` names the directory itself, so a rule set that only
        spells out descendants would leave the empty-directory form unguarded.
        """
        for path in ("evidence", "user_inputs", ".evidence", "a/b/evidence"):
            assert is_evidence_readonly_file(path) is True, path

    def test_similarly_named_paths_stay_writable(self) -> None:
        for path in ("my-evidence", "evidence_report.md", "src/evidence_handler.py"):
            assert is_evidence_readonly_file(path) is False, path


class TestSensitiveFilePatterns:
    """Verify SENSITIVE_FILE_PATTERNS tuple integrity."""

    def test_not_empty(self) -> None:
        assert len(SENSITIVE_FILE_PATTERNS) > 0

    def test_all_strings(self) -> None:
        for p in SENSITIVE_FILE_PATTERNS:
            assert isinstance(p, str)
