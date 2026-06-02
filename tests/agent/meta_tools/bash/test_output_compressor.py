"""Unit tests for output_compressor module.

Tests all compressors + entry function + safety mechanisms + failure scenarios.
Target: >= 80% coverage of output_compressor.py.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_compression(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYRM_BASH_COMPRESSION", raising=False)


@pytest.fixture()
def compress():
    from importlib import reload

    import myrm_agent_harness.agent.meta_tools.bash.output_compressor as mod

    reload(mod)
    return mod.compress_output


# ---------------------------------------------------------------------------
# Entry function tests
# ---------------------------------------------------------------------------


class TestCompressOutput:
    def test_empty_stdout_passthrough(self, compress):
        assert compress("git status", "") == ""

    def test_empty_command_passthrough(self, compress):
        assert compress("", "some output") == "some output"

    def test_unknown_command_passthrough(self, compress):
        assert compress("echo hello", "hello") == "hello"

    def test_unknown_command_passthrough_complex(self, compress):
        output = "line1\nline2\nline3"
        assert compress("python my_script.py", output) == output

    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("MYRM_BASH_COMPRESSION", "0")
        from importlib import reload

        import myrm_agent_harness.agent.meta_tools.bash.output_compressor as mod

        reload(mod)
        output = "On branch main\nnothing to commit, working tree clean\n"
        assert mod.compress_output("git status", output) == output

    def test_reenabled_after_env_change(self, monkeypatch):
        monkeypatch.setenv("MYRM_BASH_COMPRESSION", "0")
        from importlib import reload

        import myrm_agent_harness.agent.meta_tools.bash.output_compressor as mod

        reload(mod)
        output = "On branch main\nnothing to commit, working tree clean\n"
        assert mod.compress_output("git status", output) == output

        monkeypatch.delenv("MYRM_BASH_COMPRESSION")
        result = mod.compress_output("git status", output)
        assert len(result) < len(output)

    def test_failure_mode_passthrough_for_unknown(self, compress):
        output = "some unknown error output"
        assert compress("unknown_cmd", output, exit_code="1") == output

    def test_exit_code_forwarded(self, compress):
        output = (
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.13.0\n"
            "collected 5 items\n"
            "tests/test_a.py::test_x PASSED\n"
            "tests/test_b.py::test_y FAILED\n"
            "\n"
            "=================================== FAILURES ===================================\n"
            "_________________________________ test_y ______________________________________\n"
            "\n"
            "    def test_y():\n"
            ">       assert 1 == 2\n"
            "E       AssertionError: assert 1 == 2\n"
            "\n"
            "tests/test_b.py:10: AssertionError\n"
            "=========================== 1 failed, 1 passed in 0.5s ========================\n"
        )
        result = compress("pytest", output, exit_code="1")
        assert "FAILED" in result
        assert "platform linux" not in result
        assert "PASSED" not in result
        assert len(result) < len(output)


# ---------------------------------------------------------------------------
# GitStatusCompressor tests
# ---------------------------------------------------------------------------


class TestGitStatusCompressor:
    def test_clean_repo(self, compress):
        output = "On branch main\nnothing to commit, working tree clean\n"
        result = compress("git status", output)
        assert "clean" in result
        assert "branch: main" in result
        assert len(result) < len(output)

    def test_staged_changes(self, compress):
        output = (
            "On branch dev\n"
            "Changes to be committed:\n"
            '  (use "git restore --staged <file>..." to unstage)\n'
            "\tnew file:   src/new.py\n"
            "\tmodified:   src/old.py\n"
        )
        result = compress("git status", output)
        assert "staged:" in result
        assert "new file:   src/new.py" in result
        assert "modified:   src/old.py" in result
        assert '(use "git' not in result

    def test_unstaged_changes(self, compress):
        output = (
            "On branch feature\n"
            "Changes not staged for commit:\n"
            '  (use "git add <file>..." to update what will be committed)\n'
            "\tmodified:   app.py\n"
        )
        result = compress("git status", output)
        assert "unstaged:" in result
        assert "modified:   app.py" in result

    def test_untracked_files(self, compress):
        output = (
            "On branch main\n"
            "Untracked files:\n"
            '  (use "git add <file>..." to include in what will be committed)\n'
            "\ttodo.txt\n"
        )
        result = compress("git status", output)
        assert "untracked:" in result
        assert "todo.txt" in result

    def test_branch_ahead(self, compress):
        output = (
            "On branch feature\n"
            "Your branch is ahead of 'origin/feature' by 2 commits.\n"
            '  (use "git push" to publish your local commits)\n'
            "\nnothing to commit, working tree clean\n"
        )
        result = compress("git status", output)
        assert "branch: feature" in result
        assert "ahead" in result

    def test_no_git_status_content_passthrough(self, compress):
        output = "random text without git status keywords"
        assert compress("git status", output) == output


# ---------------------------------------------------------------------------
# GitDiffCompressor tests
# ---------------------------------------------------------------------------


class TestGitDiffCompressor:
    def test_removes_meta_lines(self, compress):
        output = (
            "diff --git a/x.py b/x.py\n"
            "index abc1234..def5678 100644\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-old\n"
            "+new\n"
            " context\n"
        )
        result = compress("git diff", output)
        assert "diff --git" in result  # Now we keep diff --git for filename extraction
        assert "index abc" not in result
        assert "--- a/x.py" not in result
        assert "+++ b/x.py" not in result
        assert "-old" in result
        assert "+new" in result
        assert "@@ -1,3" in result

    def test_preserves_content_with_dashes(self, compress):
        output = (
            "diff --git a/doc.md b/doc.md\n"
            "index abc..def 100644\n"
            "--- a/doc.md\n"
            "+++ b/doc.md\n"
            "@@ -1,4 +1,3 @@\n"
            " # Title\n"
            "----\n"
            "-separator\n"
            "+new content\n"
        )
        result = compress("git diff", output)
        assert "----" in result

    def test_no_diff_content_passthrough(self, compress):
        output = "Not a diff output"
        assert compress("git diff", output) == output


# ---------------------------------------------------------------------------
# GitLogCompressor tests
# ---------------------------------------------------------------------------


class TestGitLogCompressor:
    def test_extracts_short_hash_and_message(self, compress):
        output = (
            "commit abcdef1234567890123456789012345678901234\n"
            "Author: Test <test@test.com>\n"
            "Date:   Mon Apr 28 2026 10:00:00 +0800\n"
            "\n"
            "    feat: add feature\n"
            "\n"
            "commit bcdef12345678901234567890123456789012345\n"
            "Author: Dev <dev@test.com>\n"
            "Date:   Sun Apr 27 2026 09:00:00 +0800\n"
            "\n"
            "    fix: bug fix\n"
        )
        result = compress("git log -5", output)
        assert "abcdef1 feat: add feature" in result
        assert "bcdef12 fix: bug fix" in result
        assert "Author:" not in result
        assert "Date:" not in result

    def test_no_commit_passthrough(self, compress):
        output = "Not a git log output"
        assert compress("git log", output) == output


# ---------------------------------------------------------------------------
# GitOperationCompressor tests
# ---------------------------------------------------------------------------


class TestGitOperationCompressor:
    def test_commit_output(self, compress):
        output = "[main abc1234] feat: new feature\n 3 files changed, 50 insertions(+), 10 deletions(-)\n"
        result = compress("git commit -m 'feat'", output)
        assert "[main abc1234]" in result
        assert "feat: new feature" in result

    def test_push_output(self, compress):
        output = (
            "Enumerating objects: 5, done.\n"
            "Counting objects: 100% (5/5), done.\n"
            "Compressing objects: 100% (3/3), done.\n"
            "Writing objects: 100% (3/3), 1.23 KiB | 1.23 MiB/s, done.\n"
            "Total 3 (delta 2), reused 0 (delta 0), pack-reused 0\n"
            "remote: Resolving deltas: 100% (2/2)\n"
            "To github.com:user/repo.git\n"
            "   abc1234..def5678  main -> main\n"
        )
        result = compress("git push origin main", output)
        assert "Enumerating" not in result
        assert "Counting" not in result
        assert "github.com" in result
        assert "main -> main" in result

    def test_no_push_content_passthrough(self, compress):
        output = "Already up to date."
        assert compress("git pull", output) == output

    def test_push_failure_strips_counting(self, compress):
        output = (
            "Enumerating objects: 5, done.\n"
            "Counting objects: 100% (5/5), done.\n"
            "error: failed to push some refs to 'origin'\n"
            "hint: Updates were rejected because the remote contains work.\n"
        )
        result = compress("git push", output, exit_code="1")
        assert "error: failed to push" in result
        assert len(result) < len(output)

    def test_merge_conflict_failure(self, compress):
        output = (
            "Updating abc1234..def5678\n"
            "CONFLICT (content): Merge conflict in src/main.py\n"
            "Automatic merge failed; fix conflicts and then commit the result.\n"
        )
        result = compress("git merge feature", output, exit_code="1")
        assert "CONFLICT" in result
        assert "Merge conflict" in result

    def test_push_preserves_pr_url(self, compress):
        output = (
            "Enumerating objects: 5, done.\n"
            "Counting objects: 100% (5/5), done.\n"
            "Compressing objects: 100% (3/3), done.\n"
            "Writing objects: 100% (3/3), 1.2 KiB | 614 B/s, done.\n"
            "Total 3 (delta 2), reused 0 (delta 0)\n"
            "remote: Resolving deltas: 100% (2/2), completed with 2 local objects.\n"
            "remote:\n"
            "remote: Create a pull request for 'feature-auth' on GitHub by visiting:\n"
            "remote:   https://github.com/user/repo/pull/new/feature-auth\n"
            "remote:\n"
            "To github.com:user/repo.git\n"
            "   abc1234..def5678  feature-auth -> feature-auth\n"
        )
        result = compress("git push origin feature-auth", output)
        assert "pull/new/feature-auth" in result
        assert "Create a pull request" in result
        assert "Enumerating" not in result
        assert "Counting" not in result
        assert len(result) < len(output)


# ---------------------------------------------------------------------------
# LsCompressor tests
# ---------------------------------------------------------------------------


class TestLsCompressor:
    def test_macos_format(self, compress):
        output = (
            "total 128\n"
            "drwxr-xr-x  12 user  staff    384 Apr 28 10:00 .\n"
            "drwxr-xr-x   5 user  staff    160 Apr 27 09:00 ..\n"
            "-rw-r--r--   1 user  staff    256 Apr 28 10:00 README.md\n"
            "drwxr-xr-x   4 user  staff    128 Apr 28 09:45 src\n"
        )
        result = compress("ls -la", output)
        assert "README.md" in result
        assert "src/" in result
        assert "total 128" not in result
        assert "staff" not in result

    def test_linux_iso_format(self, compress):
        output = (
            "total 8\n"
            "-rw-r--r-- 1 user staff 100 2026-04-28 10:00 file1.txt\n"
            "drwxr-xr-x 2 user staff  64 2026-04-28 09:30 subdir\n"
            "-rwxr-xr-x 1 user staff 200 2026-04-28 08:00 script.sh\n"
        )
        result = compress("ls -la", output)
        assert "file1.txt" in result
        assert "subdir/" in result

    def test_extended_attrs(self, compress):
        output = (
            "total 8\n"
            "-rw-r--r--@ 1 user staff 100 Apr 28 10:00 xattr.txt\n"
            "drwxr-xr-x  2 user staff  64 Apr 28 09:30 dir\n"
            "-rw-r--r--  1 user staff  50 Apr 28 09:00 normal.txt\n"
        )
        result = compress("ls -la", output)
        assert "xattr.txt" in result
        assert "dir/" in result

    def test_too_few_lines_passthrough(self, compress):
        output = "total 0\n-rw-r--r-- 1 user staff 0 Apr 28 10:00 only.txt\n"
        assert compress("ls -la", output) == output

    def test_non_long_format_passthrough(self, compress):
        output = "file1.txt\nfile2.txt\nfile3.txt\n"
        assert compress("ls -la", output) == output


# ---------------------------------------------------------------------------
# TestCompressor tests
# ---------------------------------------------------------------------------


class TestTestCompressor:
    def test_pytest_pass(self, compress):
        output = (
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.13.0\n"
            "collected 42 items\n"
            "tests/test_a.py ....                     [ 9%]\n"
            "tests/test_b.py ..........               [33%]\n"
            "tests/test_c.py ......................   [85%]\n"
            "tests/test_d.py ......                   [100%]\n"
            "\n"
            "============================== 42 passed in 3.21s ==============================\n"
        )
        result = compress("pytest tests/", output)
        assert "42 passed" in result
        assert "3.21s" in result
        assert len(result) < 30

    def test_pytest_with_warnings(self, compress):
        output = "====== 10 passed, 2 warnings in 1.5s ======\n"
        result = compress("pytest", output)
        assert "10 passed" in result
        assert "warnings" in result

    def test_cargo_test(self, compress):
        output = (
            "running 10 tests\n"
            "test test_a ... ok\n"
            "test test_b ... ok\n"
            "\n"
            "test result: ok. 10 passed; 0 failed; 0 ignored\n"
        )
        result = compress("cargo test", output)
        assert "test result: ok" in result
        assert "10 passed" in result

    def test_go_test(self, compress):
        output = (
            "=== RUN   TestAdd\n"
            "--- PASS: TestAdd (0.00s)\n"
            "=== RUN   TestSub\n"
            "--- PASS: TestSub (0.00s)\n"
            "PASS\n"
            "ok  \tgithub.com/user/pkg\t0.005s\n"
            "ok  \tgithub.com/user/pkg2\t0.003s\n"
        )
        result = compress("go test ./...", output)
        assert "ok github.com/user/pkg" in result

    def test_pytest_failure_strips_noise(self, compress):
        output = (
            "============================= test session starts ==============================\n"
            "platform linux -- Python 3.11.0, pytest-7.4.0, pluggy-1.3.0\n"
            "rootdir: /home/user/project\n"
            "plugins: asyncio-0.21.1, cov-4.1.0, mock-3.11.1\n"
            "collected 35 items\n"
            "\n"
            "tests/test_ok.py::test_a PASSED\n"
            "tests/test_ok.py::test_b PASSED\n"
            "tests/test_ok.py::test_c PASSED\n"
            "tests/test_fail.py::test_broken FAILED\n"
            "\n"
            "=================================== FAILURES ===================================\n"
            "_________________________________ test_broken __________________________________\n"
            "\n"
            "    def test_broken():\n"
            ">       assert 1 == 2\n"
            "E       AssertionError: assert 1 == 2\n"
            "\n"
            "tests/test_fail.py:10: AssertionError\n"
            "=========================== 1 failed, 3 passed in 0.5s ========================\n"
        )
        result = compress("pytest", output, exit_code="1")
        assert "FAILED" in result
        assert "AssertionError" in result
        assert "1 failed" in result
        assert "platform linux" not in result
        assert "rootdir:" not in result
        assert "plugins:" not in result
        assert "tests/test_ok.py::test_a PASSED" not in result
        assert len(result) < len(output)

    def test_jest_failure_passthrough(self, compress):
        output = "FAIL src/__tests__/app.test.js\n  ✕ should work (5ms)\nTests: 1 failed, 0 passed\n"
        result = compress("npm test", output, exit_code="1")
        assert "FAIL" in result


# ---------------------------------------------------------------------------
# PackageInstallCompressor tests
# ---------------------------------------------------------------------------


class TestPackageInstallCompressor:
    def test_npm_install(self, compress):
        output = (
            "npm warn deprecated inflight@1.0.6: This module leaks memory.\n"
            "npm warn deprecated glob@7.2.3: Glob prior to v9 not supported.\n"
            "npm warn deprecated rimraf@3.0.2: Rimraf prior to v4 not supported.\n"
            "\n"
            "added 387 packages, and audited 388 packages in 12s\n"
            "\n"
            "found 0 vulnerabilities\n"
        )
        result = compress("npm install", output)
        assert "added 387 packages" in result
        assert "found 0 vulnerabilities" in result
        assert "deprecated" not in result
        assert len(result) < len(output)

    def test_pip_install(self, compress):
        output = (
            "Collecting requests\n"
            "  Downloading requests-2.31.0-py3-none-any.whl (62 kB)\n"
            "Collecting urllib3<3,>=1.21.1\n"
            "  Downloading urllib3-2.0.7-py3-none-any.whl (124 kB)\n"
            "Collecting charset-normalizer<4,>=2\n"
            "  Using cached charset_normalizer-3.3.2.whl (227 kB)\n"
            "Installing collected packages: urllib3, charset-normalizer, requests\n"
            "Successfully installed charset-normalizer-3.3.2 requests-2.31.0 urllib3-2.0.7\n"
        )
        result = compress("pip install requests", output)
        assert "Successfully installed 3 packages" in result
        assert "Collecting" not in result

    def test_uv_sync(self, compress):
        output = (
            "Collecting myrm-agent-harness\n"
            "Downloading myrm_agent_harness-1.0.0.tar.gz\n"
            "Building myrm-agent-harness-1.0.0\n"
            "Resolved 45 packages in 2.3s\n"
            "Installed 12 packages in 1.1s\n"
            " + myrm-agent-harness==1.0.0\n"
        )
        result = compress("uv sync --all-extras", output)
        assert "Collecting" not in result or len(result) < len(output) * 0.7

    def test_short_npm_still_compresses_when_possible(self, compress):
        output = "added 1 package in 0.5s\n"
        result = compress("npm install x", output)
        assert "added 1 package" in result
        assert len(result) <= len(output)

    def test_npm_install_failure(self, compress):
        output = (
            "Collecting some-package\n"
            "  Downloading some-package-1.0.tar.gz\n"
            "Collecting dep-a\n"
            "  Downloading dep-a-2.0.whl\n"
            "npm ERR! code ERESOLVE\n"
            "npm ERR! ERESOLVE unable to resolve dependency tree\n"
            "npm ERR! peer dep missing: react@^17, got react@^18\n"
        )
        result = compress("npm install", output, exit_code="1")
        assert "ERR!" in result
        assert len(result) < len(output)


# ---------------------------------------------------------------------------
# DockerBuildCompressor tests
# ---------------------------------------------------------------------------


class TestDockerBuildCompressor:
    def test_strips_extracting_noise(self, compress):
        lines = []
        for i in range(5):
            lines.append(f"#5 [{i + 1}/5] RUN apt-get install -y pkg-{i}")
            lines.append(f"#5 extracting sha256:abc{i}def1234567890abcdef1234567890")
            lines.append(f"#5 extracting sha256:xyz{i}def1234567890abcdef1234567890")
            lines.append(f"#5 0.{i}s done")
        lines.append("#6 [5/5] COPY . .")
        lines.append("#6 DONE 0.1s")
        lines.append(" => exporting to image")
        lines.append("writing image sha256:final1234567890")
        output = "\n".join(lines)

        result = compress("docker build .", output)
        assert "extracting sha256" not in result
        assert "RUN apt-get" in result
        assert "exporting to image" in result
        assert "writing image" in result
        assert len(result) < len(output) * 0.7

    def test_docker_build_failure(self, compress):
        output = (
            "#5 [1/3] FROM node:18\n"
            "#5 extracting sha256:abc123def456\n"
            "#5 extracting sha256:xyz789abc012\n"
            "#5 DONE 2.1s\n"
            "#6 [2/3] COPY package.json .\n"
            "#6 DONE 0.1s\n"
            "#7 [3/3] RUN npm install\n"
            "#7 ERROR: executor failed: exit code 1\n"
            "------\n"
            " > [3/3] RUN npm install:\n"
            "#7 0.5 npm ERR! code ERESOLVE\n"
            "#7 0.5 npm ERR! unable to resolve dependency tree\n"
        )
        result = compress("docker build .", output, exit_code="1")
        assert "ERROR" in result
        assert "npm ERR!" in result
        assert "extracting sha256" not in result
        assert len(result) < len(output)

    def test_buildx_also_matched(self, compress):
        output = "#1 [internal] load build definition\n#1 extracting sha256:aaabbb\n#1 DONE 0.0s\n"
        result = compress("docker buildx build .", output)
        assert "extracting sha256" not in result
        assert "DONE" in result

    def test_docker_compose_build(self, compress):
        output = (
            "#1 [internal] load build definition from Dockerfile\n"
            "#1 DONE 0.1s\n"
            "#2 [1/3] FROM python:3.13\n"
            "#2 extracting sha256:abc123def456\n"
            "#2 extracting sha256:xyz789abc012\n"
            "#2 DONE 3.0s\n"
            "#3 [2/3] COPY . /app\n"
            "#3 DONE 0.2s\n"
        )
        result = compress("docker compose build web", output)
        assert "extracting sha256" not in result
        assert "COPY . /app" in result
        assert len(result) < len(output)


# ---------------------------------------------------------------------------
# BuildToolCompressor tests
# ---------------------------------------------------------------------------


class TestBuildToolCompressor:
    def test_cargo_build_failure_strips_compiling(self, compress):
        lines = []
        for i in range(50):
            lines.append(f"   Compiling dep-{i} v0.1.0 (/path/to/dep-{i})")
        lines.append("error[E0308]: mismatched types")
        lines.append("  --> src/main.rs:42:5")
        lines.append("   |")
        lines.append('42 |     let x: i32 = "hello";')
        lines.append("   |                  ^^^^^^^ expected i32, found &str")
        lines.append("error: could not compile `myproject` due to 1 previous error")
        output = "\n".join(lines)

        result = compress("cargo build", output, exit_code="1")
        assert "Compiling dep-" not in result
        assert "error[E0308]" in result
        assert "expected i32" in result
        assert "could not compile" in result
        assert len(result) < len(output) * 0.3

    def test_cargo_build_success_passthrough(self, compress):
        output = "   Compiling myproject v0.1.0\n    Finished dev [unoptimized + debuginfo] target(s) in 2.34s\n"
        result = compress("cargo build", output)
        assert result == output

    def test_cargo_check_failure(self, compress):
        lines = []
        for i in range(20):
            lines.append(f"   Compiling dep-{i} v0.1.0")
        lines.append("error[E0425]: cannot find value `x`")
        lines.append("  --> src/lib.rs:10:5")
        output = "\n".join(lines)

        result = compress("cargo check", output, exit_code="1")
        assert "Compiling dep-" not in result
        assert "error[E0425]" in result

    def test_cargo_clippy_failure(self, compress):
        lines = []
        for i in range(30):
            lines.append(f"   Compiling dep-{i} v0.{i}.0")
        lines.append("warning: unused variable: `x`")
        lines.append("  --> src/main.rs:10:9")
        lines.append("error: aborting due to 1 previous error")
        output = "\n".join(lines)

        result = compress("cargo clippy", output, exit_code="1")
        assert "Compiling dep-" not in result
        assert "unused variable" in result
        assert "error: aborting" in result
        assert len(result) < len(output) * 0.3

    def test_cargo_run_compile_failure(self, compress):
        lines = []
        for i in range(20):
            lines.append(f"   Compiling dep-{i} v0.{i}.0")
        lines.append("error[E0425]: cannot find value `foo` in this scope")
        lines.append("  --> src/main.rs:5:5")
        lines.append("error: aborting due to 1 previous error")
        output = "\n".join(lines)

        result = compress("cargo run", output, exit_code="1")
        assert "Compiling dep-" not in result
        assert "error[E0425]" in result

    def test_cargo_run_success_passthrough(self, compress):
        output = (
            "   Compiling myproject v0.1.0\n"
            "    Finished dev [unoptimized + debuginfo] target(s) in 0.5s\n"
            "     Running `target/debug/myproject`\n"
            "Hello, world!\n"
        )
        result = compress("cargo run", output)
        assert result == output


# ---------------------------------------------------------------------------
# Edge cases and safety
# ---------------------------------------------------------------------------


class TestSafety:
    def test_compressor_exception_passthrough(self, compress, monkeypatch):
        from myrm_agent_harness.agent.meta_tools.bash import output_compressor as mod

        original_registry = mod._COMPRESSOR_REGISTRY

        class BrokenCompressor:
            def compress(self, stdout: str, *, is_failure: bool = False) -> str | None:
                raise RuntimeError("boom")

        monkeypatch.setattr(
            mod,
            "_COMPRESSOR_REGISTRY",
            [(original_registry[0][0], BrokenCompressor()), *original_registry[1:]],
        )

        output = "On branch main\nnothing to commit, working tree clean\n"
        result = mod.compress_output("git status", output)
        assert result == output

    def test_compression_never_grows_output(self, compress):
        commands_and_outputs = [
            ("git status", "On branch x\nChanges not staged for commit:\n\tmodified: a\n"),
            ("git diff", "diff --git a/x b/x\nindex a..b 100\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"),
            ("git log", "commit abc123\nAuthor: A\nDate: D\n\n    msg\n"),
            (
                "ls -la /tmp",
                "total 0\n-rw-r--r-- 1 u g 0 Apr 1 10:00 a\n-rw-r--r-- 1 u g 0 Apr 1 10:00 b\ndrwxr-xr-x 1 u g 0 Apr 1 10:00 c\n",
            ),
        ]
        for cmd, output in commands_and_outputs:
            result = compress(cmd, output)
            assert len(result) <= len(output), f"Compression grew output for: {cmd}"

    def test_failure_compression_never_grows_output(self, compress):
        commands_and_outputs = [
            ("pytest", "FAILED tests/test_x.py::test_a - assert 1 == 2\n1 failed in 0.1s\n"),
            ("npm install", "npm ERR! code ERESOLVE\nnpm ERR! unable to resolve\n"),
            ("git push", "error: failed to push some refs\nhint: Try pulling first.\n"),
            ("docker build .", "#1 ERROR: some error\n"),
        ]
        for cmd, output in commands_and_outputs:
            result = compress(cmd, output, exit_code="1")
            assert len(result) <= len(output), f"Failure compression grew output for: {cmd}"


# ---------------------------------------------------------------------------
# CompilerErrorCompressor tests
# ---------------------------------------------------------------------------


class TestCompilerErrorCompressor:
    def test_tsc_error_compression(self, compress):
        output = (
            "src/app/layout.tsx(10,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
            "  10 | const a: number = 'hello';\n"
            "     |       ^\n"
            "src/components/Button.tsx(15,10): error TS2304: Cannot find name 'React'.\n"
            "  15 | return <React.Fragment />;\n"
            "     |          ^^^^^\n"
            "src/components/Button.tsx(20,5): warning TS6133: 'unused' is declared but its value is never read.\n"
        )
        result = compress("tsc --noEmit", output, exit_code="1")
        assert "Compiler output aggregated for clarity" in result
        assert "src/app/layout.tsx:" in result
        assert "Line 10: [TS2322] Type 'string' is not assignable to type 'number'." in result
        assert "src/components/Button.tsx:" in result
        assert "Line 15: [TS2304] Cannot find name 'React'." in result
        assert "TS6133" not in result  # Warnings are ignored
        assert "const a: number" not in result  # Code snippets are dropped
        assert "Summary: Found 2 errors across 2 files." in result

    def test_eslint_error_compression(self, compress):
        output = (
            (
                "\n"
                "/Users/project/src/app.ts\n"
                "  10:5  error  'foo' is assigned a value but never used  no-unused-vars\n"
                "  11:5  error  'foo2' is assigned a value but never used  no-unused-vars\n"
                "  12:5  error  'foo3' is assigned a value but never used  no-unused-vars\n"
                "  13:5  error  'foo4' is assigned a value but never used  no-unused-vars\n"
                "  20:1  warning  Missing trailing comma                    comma-dangle\n"
                "\n"
                "/Users/project/src/utils.ts\n"
                "  5:10  error  'bar' is not defined                      no-undef\n"
                "  6:10  error  'bar2' is not defined                      no-undef\n"
                "  7:10  error  'bar3' is not defined                      no-undef\n"
                "  8:10  error  'bar4' is not defined                      no-undef\n"
                "\n"
                "✖ 9 problems (8 errors, 1 warning)\n"
                "  8 errors and 0 warnings potentially fixable with the `--fix` option.\n"
                "  Some more long text that makes the original output much longer than the compressed one.\n"
                "  This ensures the compression ratio is met.\n"
            )
            + "  " * 20
            + "\n"
        )
        result = compress("eslint .", output, exit_code="1")
        assert "Compiler output aggregated for clarity" in result
        assert "/Users/project/src/app.ts:" in result
        assert "Line 10: [no-unused-vars] 'foo' is assigned a value but never used" in result
        assert "/Users/project/src/utils.ts:" in result
        assert "Line 5: [no-undef] 'bar' is not defined" in result
        assert "comma-dangle" not in result  # Warnings are ignored
        assert "Summary: Found 8 errors across 2 files." in result

    def test_compiler_success_passthrough(self, compress):
        output = "Done in 1.5s.\n"
        result = compress("tsc --noEmit", output, exit_code="0")
        assert result == output

    def test_compiler_no_errors_passthrough(self, compress):
        output = "Some random output without errors.\n"
        result = compress("tsc --noEmit", output, exit_code="1")
        assert result == output

    def test_compiler_too_many_errors(self, compress):
        lines = []
        for i in range(50):
            lines.append(
                f"src/file{i}.ts(1,1): error TS1000: Error {i} with a very long message to make sure the original output is much longer than the compressed output which truncates after 20 errors. This padding ensures we meet the 0.95 ratio requirement."
            )
        output = "\n".join(lines)
        result = compress("tsc --noEmit", output, exit_code="1")
        assert "Showing first 20 errors out of 50." in result
        assert "src/file19.ts:" in result
        assert "src/file20.ts:" not in result


# ---------------------------------------------------------------------------
# LogCompressor tests
# ---------------------------------------------------------------------------


class TestLogCompressor:
    def test_massive_repetitive_logs(self):
        from myrm_agent_harness.agent.meta_tools.bash.output_compressor import LogCompressor

        compressor = LogCompressor()
        lines = []
        for i in range(200):
            lines.append(
                f"2026-05-21 10:00:01.{i:03d} ERROR 12345 --- [main] com.zaxxer.hikari.pool.HikariPool : Connection refused to 127.0.0.1:5432"
            )
        for i in range(50):
            lines.append(f"2026-05-21 10:00:02.{i:03d} WARN 12345 --- [main] com.example.App : Retrying connection...")

        output = "\n".join(lines)
        result = compressor.compress(output)

        assert result is not None
        assert "Auto-deduplicated" in result
        assert "[error] 200 errors (1 unique)" in result
        assert "[warn] 50 warnings (1 unique)" in result
        assert "[×200]" in result
        assert "[×50]" in result
        assert "Connection refused" in result
        assert "Retrying connection" in result
        assert len(result) < len(output) * 0.1

    def test_non_repetitive_logs_passthrough(self):
        from myrm_agent_harness.agent.meta_tools.bash.output_compressor import LogCompressor

        compressor = LogCompressor()
        lines = []
        for i in range(150):
            lines.append(f"2026-05-21 10:00:01 INFO : Processed item {i} abcdefg")

        output = "\n".join(lines)
        result = compressor.compress(output)
        assert result is None  # Should return None because unique_total > len * 0.5

    def test_short_logs_passthrough(self):
        from myrm_agent_harness.agent.meta_tools.bash.output_compressor import LogCompressor

        compressor = LogCompressor()
        lines = []
        for i in range(50):
            lines.append(
                f"2026-05-21 10:00:01.{i:03d} ERROR 12345 --- [main] com.zaxxer.hikari.pool.HikariPool : Connection refused"
            )

        output = "\n".join(lines)
        result = compressor.compress(output)
        assert result is None

    def test_single_count_and_empty_lines(self):
        from myrm_agent_harness.agent.meta_tools.bash.output_compressor import LogCompressor

        compressor = LogCompressor()
        lines = []
        for i in range(100):
            lines.append(
                f"2026-05-21 10:00:01.{i:03d} ERROR 12345 --- [main] com.zaxxer.hikari.pool.HikariPool : Connection refused to 127.0.0.1:5432"
            )

        # Add a single unique error and warning
        lines.append("2026-05-21 10:00:01.000 ERROR 12345 --- [main] com.example.App : Unique error")
        lines.append("2026-05-21 10:00:01.000 WARN 12345 --- [main] com.example.App : Unique warning")
        lines.append("2026-05-21 10:00:01.000 INFO 12345 --- [main] com.example.App : Just some info")
        lines.append("2026-05-21 10:00:01.000 INFO 12345 --- [main] com.example.App : Just some info")
        lines.append("")  # Empty line (will become empty normalized string)
        lines.append("2026-05-21 10:00:01.000")  # Just timestamp (will become empty normalized string)

        output = "\n".join(lines)
        result = compressor.compress(output)

        assert result is not None
        assert "Unique error" in result
        assert "Unique warning" in result
        assert "[info] 2 info messages" in result
        assert "[×100]" in result
        assert "[×1]" not in result  # single count shouldn't have multiplier
