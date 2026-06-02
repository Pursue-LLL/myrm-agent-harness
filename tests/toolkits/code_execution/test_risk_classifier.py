"""Tests for command risk classifier."""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
    SAFE_COMMANDS,
    CommandRiskLevel,
    classify_command_risk,
)


class TestClassifyCommandRisk:
    """Core classification logic."""

    def test_simple_safe_command(self) -> None:
        assert classify_command_risk("ls") == CommandRiskLevel.SAFE

    def test_safe_command_with_flags(self) -> None:
        assert classify_command_risk("ls -la") == CommandRiskLevel.SAFE

    def test_safe_command_with_path(self) -> None:
        assert classify_command_risk("cat /tmp/foo.txt") == CommandRiskLevel.SAFE

    def test_unknown_command(self) -> None:
        assert classify_command_risk("rm -rf /tmp/foo") == CommandRiskLevel.UNKNOWN

    def test_empty_command(self) -> None:
        assert classify_command_risk("") == CommandRiskLevel.UNKNOWN

    def test_whitespace_only(self) -> None:
        assert classify_command_risk("   ") == CommandRiskLevel.UNKNOWN


class TestPipelineSplitting:
    """Pipeline handling."""

    def test_safe_pipeline(self) -> None:
        assert classify_command_risk("ls -la | grep foo") == CommandRiskLevel.SAFE

    def test_safe_triple_pipeline(self) -> None:
        assert classify_command_risk("cat file | sort | uniq") == CommandRiskLevel.SAFE

    def test_unsafe_pipeline_segment(self) -> None:
        assert classify_command_risk("ls | rm -rf /") == CommandRiskLevel.UNKNOWN

    def test_empty_pipeline_segment(self) -> None:
        assert classify_command_risk("ls |  | grep foo") == CommandRiskLevel.UNKNOWN


class TestRedirectDetection:
    """I/O redirect blocking."""

    def test_output_redirect(self) -> None:
        assert classify_command_risk("echo hello > file.txt") == CommandRiskLevel.UNKNOWN

    def test_append_redirect(self) -> None:
        assert classify_command_risk("echo hello >> file.txt") == CommandRiskLevel.UNKNOWN

    def test_input_redirect(self) -> None:
        assert classify_command_risk("cat < input.txt") == CommandRiskLevel.UNKNOWN

    def test_redirect_to_dangerous_path(self) -> None:
        assert classify_command_risk("cat > /etc/passwd") == CommandRiskLevel.UNKNOWN


class TestEnvVarAssignment:
    """Leading env var assignments should be skipped."""

    def test_env_prefix_safe(self) -> None:
        assert classify_command_risk("FOO=bar ls") == CommandRiskLevel.SAFE

    def test_env_prefix_unsafe(self) -> None:
        assert classify_command_risk("FOO=bar rm file") == CommandRiskLevel.UNKNOWN


class TestExcludedCommands:
    """Commands that should NOT be in SAFE_COMMANDS."""

    def test_git_not_safe(self) -> None:
        assert classify_command_risk("git push origin main") == CommandRiskLevel.UNKNOWN

    def test_rm_not_safe(self) -> None:
        assert classify_command_risk("rm file.txt") == CommandRiskLevel.UNKNOWN

    def test_curl_not_safe(self) -> None:
        assert classify_command_risk("curl https://example.com") == CommandRiskLevel.UNKNOWN

    def test_wget_not_safe(self) -> None:
        assert classify_command_risk("wget https://example.com") == CommandRiskLevel.UNKNOWN

    def test_pip_not_safe(self) -> None:
        assert classify_command_risk("pip install requests") == CommandRiskLevel.UNKNOWN

    def test_npm_install_bare_safe(self) -> None:
        assert classify_command_risk("npm install") == CommandRiskLevel.SAFE

    def test_npm_install_pkg_not_safe(self) -> None:
        assert classify_command_risk("npm install lodash") == CommandRiskLevel.UNKNOWN

    def test_python_not_safe(self) -> None:
        assert classify_command_risk("python3 script.py") == CommandRiskLevel.UNKNOWN

    def test_sudo_not_safe(self) -> None:
        assert classify_command_risk("sudo ls") == CommandRiskLevel.UNKNOWN

    def test_sed_not_safe(self) -> None:
        assert classify_command_risk("sed -i 's/foo/bar/' file.txt") == CommandRiskLevel.UNKNOWN

    def test_awk_not_safe(self) -> None:
        assert classify_command_risk("awk '{print}'") == CommandRiskLevel.UNKNOWN

    def test_find_read_only_safe(self) -> None:
        assert classify_command_risk("find . -name '*.py'") == CommandRiskLevel.SAFE

    def test_find_exec_not_safe(self) -> None:
        assert classify_command_risk("find . -exec rm {} \\;") == CommandRiskLevel.UNKNOWN

    def test_find_delete_not_safe(self) -> None:
        assert classify_command_risk("find . -delete") == CommandRiskLevel.UNKNOWN

    def test_tee_not_safe(self) -> None:
        assert classify_command_risk("echo hi | tee file.txt") == CommandRiskLevel.UNKNOWN

    def test_ssh_not_safe(self) -> None:
        assert classify_command_risk("ssh user@host") == CommandRiskLevel.UNKNOWN


class TestAbsolutePathCommand:
    """Full path to safe command should still work."""

    def test_absolute_path_ls(self) -> None:
        assert classify_command_risk("/bin/ls -la") == CommandRiskLevel.SAFE

    def test_absolute_path_cat(self) -> None:
        assert classify_command_risk("/usr/bin/cat file.txt") == CommandRiskLevel.SAFE


class TestSafeCommandsCoverage:
    """Verify all safe commands are correctly classified."""

    def test_all_safe_commands_classified_safe(self) -> None:
        for cmd in sorted(SAFE_COMMANDS):
            result = classify_command_risk(cmd)
            assert result == CommandRiskLevel.SAFE, f"{cmd} should be SAFE but got {result}"


class TestShellOperatorSplitting:
    """Tests for _split_shell_operators: &&, ||, |, quote-awareness."""

    def test_and_operator_safe_both(self) -> None:
        assert classify_command_risk("ls && pwd") == CommandRiskLevel.SAFE

    def test_and_operator_unsafe_second(self) -> None:
        assert classify_command_risk("ls && rm -rf /tmp/evil") == CommandRiskLevel.UNKNOWN

    def test_or_operator_safe_both(self) -> None:
        assert classify_command_risk("ls || pwd") == CommandRiskLevel.SAFE

    def test_or_operator_unsafe_second(self) -> None:
        assert classify_command_risk("ls || rm file") == CommandRiskLevel.UNKNOWN

    def test_mixed_operators(self) -> None:
        assert classify_command_risk("ls && pwd || echo done") == CommandRiskLevel.SAFE

    def test_double_quoted_and_not_split(self) -> None:
        assert classify_command_risk('echo "a && b"') == CommandRiskLevel.SAFE

    def test_double_quoted_pipe_not_split(self) -> None:
        assert classify_command_risk('echo "a | b"') == CommandRiskLevel.SAFE

    def test_double_quoted_or_not_split(self) -> None:
        assert classify_command_risk('echo "a || b"') == CommandRiskLevel.SAFE

    def test_single_quoted_and_not_split(self) -> None:
        assert classify_command_risk("echo 'a && b'") == CommandRiskLevel.SAFE

    def test_backslash_escape_in_double_quotes(self) -> None:
        assert classify_command_risk('echo "path\\"s && more"') == CommandRiskLevel.SAFE

    def test_and_with_git_safe(self) -> None:
        assert classify_command_risk("git status && git log --oneline") == CommandRiskLevel.SAFE

    def test_and_with_git_unsafe(self) -> None:
        assert classify_command_risk("git status && git push") == CommandRiskLevel.UNKNOWN

    def test_triple_and(self) -> None:
        assert classify_command_risk("ls && pwd && whoami") == CommandRiskLevel.SAFE

    def test_pipe_and_and(self) -> None:
        assert classify_command_risk("cat file | grep foo && echo done") == CommandRiskLevel.SAFE

    def test_pipe_and_and_unsafe(self) -> None:
        assert classify_command_risk("cat file | grep foo && rm file") == CommandRiskLevel.UNKNOWN


class TestNewToolClassification:
    """Tests for newly added tool configurations (npm/pip/docker/cargo/etc.)."""

    def test_npm_list(self) -> None:
        assert classify_command_risk("npm list") == CommandRiskLevel.SAFE

    def test_npm_list_global(self) -> None:
        assert classify_command_risk("npm list -g") == CommandRiskLevel.SAFE

    def test_npm_outdated(self) -> None:
        assert classify_command_risk("npm outdated") == CommandRiskLevel.SAFE

    def test_npm_run_safe_script(self) -> None:
        assert classify_command_risk("npm run build") == CommandRiskLevel.SAFE

    def test_npm_run_arbitrary_unknown(self) -> None:
        assert classify_command_risk("npm run deploy") == CommandRiskLevel.UNKNOWN

    def test_npm_publish_unknown(self) -> None:
        assert classify_command_risk("npm publish") == CommandRiskLevel.UNKNOWN

    def test_bun_install_bare_safe(self) -> None:
        assert classify_command_risk("bun install") == CommandRiskLevel.SAFE

    def test_bun_install_pkg_unknown(self) -> None:
        assert classify_command_risk("bun install lodash") == CommandRiskLevel.UNKNOWN

    def test_pnpm_list(self) -> None:
        assert classify_command_risk("pnpm list") == CommandRiskLevel.SAFE

    def test_pnpm_install_bare_safe(self) -> None:
        assert classify_command_risk("pnpm install") == CommandRiskLevel.SAFE

    def test_pnpm_install_pkg_unknown(self) -> None:
        assert classify_command_risk("pnpm install react") == CommandRiskLevel.UNKNOWN

    def test_pip_list(self) -> None:
        assert classify_command_risk("pip list") == CommandRiskLevel.SAFE

    def test_pip_list_outdated(self) -> None:
        assert classify_command_risk("pip list --outdated") == CommandRiskLevel.SAFE

    def test_pip_show(self) -> None:
        assert classify_command_risk("pip show requests") == CommandRiskLevel.SAFE

    def test_pip_freeze(self) -> None:
        assert classify_command_risk("pip freeze") == CommandRiskLevel.SAFE

    def test_pip_check(self) -> None:
        assert classify_command_risk("pip check") == CommandRiskLevel.SAFE

    def test_pip_install_requirements_safe(self) -> None:
        assert classify_command_risk("pip install -r requirements.txt") == CommandRiskLevel.SAFE

    def test_pip_install_editable_unknown(self) -> None:
        assert classify_command_risk("pip install -e .") == CommandRiskLevel.UNKNOWN

    def test_pip_install_editable_path_unknown(self) -> None:
        assert classify_command_risk("pip install -e /some/other/path") == CommandRiskLevel.UNKNOWN

    def test_pip_install_pkg_unknown(self) -> None:
        assert classify_command_risk("pip install requests") == CommandRiskLevel.UNKNOWN

    def test_pip3_list(self) -> None:
        assert classify_command_risk("pip3 list") == CommandRiskLevel.SAFE

    def test_uv_sync(self) -> None:
        assert classify_command_risk("uv sync") == CommandRiskLevel.SAFE

    def test_uv_sync_all_extras(self) -> None:
        assert classify_command_risk("uv sync --all-extras") == CommandRiskLevel.SAFE

    def test_uv_lock(self) -> None:
        assert classify_command_risk("uv lock") == CommandRiskLevel.SAFE

    def test_uv_pip_list(self) -> None:
        assert classify_command_risk("uv pip list") == CommandRiskLevel.SAFE

    def test_uv_pip_show(self) -> None:
        assert classify_command_risk("uv pip show requests") == CommandRiskLevel.SAFE

    def test_uv_version(self) -> None:
        assert classify_command_risk("uv version") == CommandRiskLevel.SAFE

    def test_uv_add_unknown(self) -> None:
        assert classify_command_risk("uv add requests") == CommandRiskLevel.UNKNOWN

    def test_docker_ps(self) -> None:
        assert classify_command_risk("docker ps") == CommandRiskLevel.SAFE

    def test_docker_ps_all(self) -> None:
        assert classify_command_risk("docker ps -a") == CommandRiskLevel.SAFE

    def test_docker_images(self) -> None:
        assert classify_command_risk("docker images") == CommandRiskLevel.SAFE

    def test_docker_logs(self) -> None:
        assert classify_command_risk("docker logs my-container") == CommandRiskLevel.SAFE

    def test_docker_inspect(self) -> None:
        assert classify_command_risk("docker inspect my-container") == CommandRiskLevel.SAFE

    def test_docker_run_unknown(self) -> None:
        assert classify_command_risk("docker run ubuntu") == CommandRiskLevel.UNKNOWN

    def test_docker_rm_unknown(self) -> None:
        assert classify_command_risk("docker rm my-container") == CommandRiskLevel.UNKNOWN

    def test_kubectl_get_pods(self) -> None:
        assert classify_command_risk("kubectl get pods") == CommandRiskLevel.SAFE

    def test_kubectl_describe(self) -> None:
        assert classify_command_risk("kubectl describe pod my-pod") == CommandRiskLevel.SAFE

    def test_kubectl_logs(self) -> None:
        assert classify_command_risk("kubectl logs my-pod") == CommandRiskLevel.SAFE

    def test_kubectl_apply_unknown(self) -> None:
        assert classify_command_risk("kubectl apply -f deploy.yaml") == CommandRiskLevel.UNKNOWN

    def test_kubectl_delete_unknown(self) -> None:
        assert classify_command_risk("kubectl delete pod my-pod") == CommandRiskLevel.UNKNOWN

    def test_cargo_build(self) -> None:
        assert classify_command_risk("cargo build") == CommandRiskLevel.SAFE

    def test_cargo_build_release(self) -> None:
        assert classify_command_risk("cargo build --release") == CommandRiskLevel.SAFE

    def test_cargo_check(self) -> None:
        assert classify_command_risk("cargo check") == CommandRiskLevel.SAFE

    def test_cargo_test(self) -> None:
        assert classify_command_risk("cargo test") == CommandRiskLevel.SAFE

    def test_cargo_clippy(self) -> None:
        assert classify_command_risk("cargo clippy") == CommandRiskLevel.SAFE

    def test_cargo_doc(self) -> None:
        assert classify_command_risk("cargo doc") == CommandRiskLevel.SAFE

    def test_cargo_tree(self) -> None:
        assert classify_command_risk("cargo tree") == CommandRiskLevel.SAFE

    def test_cargo_publish_unknown(self) -> None:
        assert classify_command_risk("cargo publish") == CommandRiskLevel.UNKNOWN

    def test_npx_unknown(self) -> None:
        assert classify_command_risk("npx create-react-app my-app") == CommandRiskLevel.UNKNOWN

    def test_bunx_unknown(self) -> None:
        assert classify_command_risk("bunx shadcn add button") == CommandRiskLevel.UNKNOWN


class TestGoToolChain:
    """Tests for Go ecosystem safe command configs."""

    def test_go_build(self) -> None:
        assert classify_command_risk("go build ./...") == CommandRiskLevel.SAFE

    def test_go_build_verbose(self) -> None:
        assert classify_command_risk("go build -v -race ./...") == CommandRiskLevel.SAFE

    def test_go_build_output(self) -> None:
        assert classify_command_risk("go build -o myapp ./cmd") == CommandRiskLevel.SAFE

    def test_go_test(self) -> None:
        assert classify_command_risk("go test ./...") == CommandRiskLevel.SAFE

    def test_go_test_verbose_race(self) -> None:
        assert classify_command_risk("go test -v -race -count=1 ./...") == CommandRiskLevel.SAFE

    def test_go_test_cover(self) -> None:
        assert classify_command_risk("go test -cover -coverprofile=coverage.out ./...") == CommandRiskLevel.SAFE

    def test_go_vet(self) -> None:
        assert classify_command_risk("go vet ./...") == CommandRiskLevel.SAFE

    def test_go_fmt(self) -> None:
        assert classify_command_risk("go fmt ./...") == CommandRiskLevel.SAFE

    def test_go_mod_tidy(self) -> None:
        assert classify_command_risk("go mod tidy") == CommandRiskLevel.SAFE

    def test_go_mod_download(self) -> None:
        assert classify_command_risk("go mod download") == CommandRiskLevel.SAFE

    def test_go_mod_verify(self) -> None:
        assert classify_command_risk("go mod verify") == CommandRiskLevel.SAFE

    def test_go_list(self) -> None:
        assert classify_command_risk("go list -m all") == CommandRiskLevel.SAFE

    def test_go_version(self) -> None:
        assert classify_command_risk("go version") == CommandRiskLevel.SAFE

    def test_go_env(self) -> None:
        assert classify_command_risk("go env -json") == CommandRiskLevel.SAFE

    def test_go_doc(self) -> None:
        assert classify_command_risk("go doc fmt.Println") == CommandRiskLevel.SAFE

    def test_go_clean(self) -> None:
        assert classify_command_risk("go clean -testcache") == CommandRiskLevel.SAFE

    def test_go_run_unknown(self) -> None:
        assert classify_command_risk("go run main.go") == CommandRiskLevel.UNKNOWN

    def test_go_install_unknown(self) -> None:
        assert classify_command_risk("go install golang.org/x/tools/...") == CommandRiskLevel.UNKNOWN

    def test_go_unknown_flag(self) -> None:
        assert classify_command_risk("go build --super-dangerous") == CommandRiskLevel.UNKNOWN


class TestYarnToolChain:
    """Tests for Yarn safe command configs."""

    def test_yarn_install_bare(self) -> None:
        assert classify_command_risk("yarn install") == CommandRiskLevel.SAFE

    def test_yarn_install_frozen(self) -> None:
        assert classify_command_risk("yarn install --frozen-lockfile") == CommandRiskLevel.SAFE

    def test_yarn_install_pkg_unknown(self) -> None:
        assert classify_command_risk("yarn install lodash") == CommandRiskLevel.UNKNOWN

    def test_yarn_list(self) -> None:
        assert classify_command_risk("yarn list") == CommandRiskLevel.SAFE

    def test_yarn_info(self) -> None:
        assert classify_command_risk("yarn info react") == CommandRiskLevel.SAFE

    def test_yarn_why(self) -> None:
        assert classify_command_risk("yarn why lodash") == CommandRiskLevel.SAFE

    def test_yarn_outdated(self) -> None:
        assert classify_command_risk("yarn outdated") == CommandRiskLevel.SAFE

    def test_yarn_audit(self) -> None:
        assert classify_command_risk("yarn audit") == CommandRiskLevel.SAFE

    def test_yarn_run_test(self) -> None:
        assert classify_command_risk("yarn run test") == CommandRiskLevel.SAFE

    def test_yarn_run_build(self) -> None:
        assert classify_command_risk("yarn run build") == CommandRiskLevel.SAFE

    def test_yarn_run_arbitrary_unknown(self) -> None:
        assert classify_command_risk("yarn run deploy") == CommandRiskLevel.UNKNOWN

    def test_yarn_test(self) -> None:
        assert classify_command_risk("yarn test") == CommandRiskLevel.SAFE

    def test_yarn_build(self) -> None:
        assert classify_command_risk("yarn build") == CommandRiskLevel.SAFE

    def test_yarn_add_unknown(self) -> None:
        assert classify_command_risk("yarn add react") == CommandRiskLevel.UNKNOWN

    def test_yarn_remove_unknown(self) -> None:
        assert classify_command_risk("yarn remove react") == CommandRiskLevel.UNKNOWN


class TestFindCommand:
    """Tests for find command flag-level validation."""

    def test_find_name(self) -> None:
        assert classify_command_risk("find . -name '*.py'") == CommandRiskLevel.SAFE

    def test_find_iname(self) -> None:
        assert classify_command_risk("find . -iname '*.js'") == CommandRiskLevel.SAFE

    def test_find_type_file(self) -> None:
        assert classify_command_risk("find . -type f") == CommandRiskLevel.SAFE

    def test_find_maxdepth_name(self) -> None:
        assert classify_command_risk("find . -maxdepth 2 -name '*.ts'") == CommandRiskLevel.SAFE

    def test_find_mtime(self) -> None:
        assert classify_command_risk("find /tmp -mtime -7") == CommandRiskLevel.SAFE

    def test_find_size(self) -> None:
        assert classify_command_risk("find . -size +10M") == CommandRiskLevel.SAFE

    def test_find_empty(self) -> None:
        assert classify_command_risk("find . -empty") == CommandRiskLevel.SAFE

    def test_find_regex(self) -> None:
        assert classify_command_risk("find . -regex '.*\\.py$'") == CommandRiskLevel.SAFE

    def test_find_logical_operators(self) -> None:
        assert classify_command_risk("find . -name '*.py' -or -name '*.js'") == CommandRiskLevel.SAFE

    def test_find_print(self) -> None:
        assert classify_command_risk("find . -name '*.log' -print") == CommandRiskLevel.SAFE

    def test_find_print0(self) -> None:
        assert classify_command_risk("find . -name '*.log' -print0") == CommandRiskLevel.SAFE

    def test_find_exec_blocked(self) -> None:
        assert classify_command_risk("find . -exec rm {} \\;") == CommandRiskLevel.UNKNOWN

    def test_find_execdir_blocked(self) -> None:
        assert classify_command_risk("find . -execdir cat {} \\;") == CommandRiskLevel.UNKNOWN

    def test_find_delete_blocked(self) -> None:
        assert classify_command_risk("find . -delete") == CommandRiskLevel.UNKNOWN

    def test_find_ok_blocked(self) -> None:
        assert classify_command_risk("find . -ok rm {} \\;") == CommandRiskLevel.UNKNOWN

    def test_find_complex_safe(self) -> None:
        assert (
            classify_command_risk("find . -maxdepth 3 -type f -name '*.py' -not -path '*/node_modules/*'")
            == CommandRiskLevel.SAFE
        )


class TestDockerCompose:
    """Tests for docker compose subcommands."""

    def test_docker_compose_ps(self) -> None:
        assert classify_command_risk("docker compose ps") == CommandRiskLevel.SAFE

    def test_docker_compose_logs(self) -> None:
        assert classify_command_risk("docker compose logs -f") == CommandRiskLevel.SAFE

    def test_docker_compose_config(self) -> None:
        assert classify_command_risk("docker compose config") == CommandRiskLevel.SAFE

    def test_docker_compose_images(self) -> None:
        assert classify_command_risk("docker compose images") == CommandRiskLevel.SAFE

    def test_docker_compose_build(self) -> None:
        assert classify_command_risk("docker compose build") == CommandRiskLevel.SAFE

    def test_docker_compose_up_unknown(self) -> None:
        assert classify_command_risk("docker compose up") == CommandRiskLevel.UNKNOWN

    def test_docker_compose_down_unknown(self) -> None:
        assert classify_command_risk("docker compose down") == CommandRiskLevel.UNKNOWN


class TestNpmRunScripts:
    """Tests for npm/bun/pnpm run script whitelist."""

    def test_npm_run_test(self) -> None:
        assert classify_command_risk("npm run test") == CommandRiskLevel.SAFE

    def test_npm_run_lint(self) -> None:
        assert classify_command_risk("npm run lint") == CommandRiskLevel.SAFE

    def test_npm_run_start(self) -> None:
        assert classify_command_risk("npm run start") == CommandRiskLevel.SAFE

    def test_npm_run_dev(self) -> None:
        assert classify_command_risk("npm run dev") == CommandRiskLevel.SAFE

    def test_npm_run_format(self) -> None:
        assert classify_command_risk("npm run format") == CommandRiskLevel.SAFE

    def test_npm_run_typecheck(self) -> None:
        assert classify_command_risk("npm run typecheck") == CommandRiskLevel.SAFE

    def test_npm_run_coverage(self) -> None:
        assert classify_command_risk("npm run coverage") == CommandRiskLevel.SAFE

    def test_npm_run_deploy_blocked(self) -> None:
        assert classify_command_risk("npm run deploy") == CommandRiskLevel.UNKNOWN

    def test_npm_run_custom_blocked(self) -> None:
        assert classify_command_risk("npm run my-custom-script") == CommandRiskLevel.UNKNOWN

    def test_npm_test(self) -> None:
        assert classify_command_risk("npm test") == CommandRiskLevel.SAFE

    def test_bun_run_test(self) -> None:
        assert classify_command_risk("bun run test") == CommandRiskLevel.SAFE

    def test_bun_run_build(self) -> None:
        assert classify_command_risk("bun run build") == CommandRiskLevel.SAFE

    def test_bun_run_arbitrary_blocked(self) -> None:
        assert classify_command_risk("bun run deploy") == CommandRiskLevel.UNKNOWN

    def test_pnpm_run_test(self) -> None:
        assert classify_command_risk("pnpm run test") == CommandRiskLevel.SAFE

    def test_pnpm_run_build(self) -> None:
        assert classify_command_risk("pnpm run build") == CommandRiskLevel.SAFE

    def test_pnpm_test(self) -> None:
        assert classify_command_risk("pnpm test") == CommandRiskLevel.SAFE

    def test_pnpm_run_arbitrary_blocked(self) -> None:
        assert classify_command_risk("pnpm run deploy") == CommandRiskLevel.UNKNOWN


class TestDangerousCommandsNotSafe:
    """Verify commands removed from SAFE_COMMANDS are correctly classified."""

    def test_cp_not_safe(self) -> None:
        assert classify_command_risk("cp file.txt /tmp/") == CommandRiskLevel.UNKNOWN

    def test_mv_not_safe(self) -> None:
        assert classify_command_risk("mv file.txt /tmp/") == CommandRiskLevel.UNKNOWN

    def test_xargs_not_safe(self) -> None:
        assert classify_command_risk("xargs rm") == CommandRiskLevel.UNKNOWN

    def test_ln_not_safe(self) -> None:
        assert classify_command_risk("ln -s /etc/passwd link") == CommandRiskLevel.UNKNOWN

    def test_tee_not_safe(self) -> None:
        assert classify_command_risk("echo hi | tee file.txt") == CommandRiskLevel.UNKNOWN

    def test_open_not_safe(self) -> None:
        assert classify_command_risk("open https://evil.com") == CommandRiskLevel.UNKNOWN


class TestNewSafeCommands:
    """Verify newly added SAFE_COMMANDS are correctly classified."""

    def test_pytest_safe(self) -> None:
        assert classify_command_risk("pytest -v tests/") == CommandRiskLevel.SAFE

    def test_jest_safe(self) -> None:
        assert classify_command_risk("jest") == CommandRiskLevel.SAFE

    def test_vitest_safe(self) -> None:
        assert classify_command_risk("vitest") == CommandRiskLevel.SAFE

    def test_eslint_safe(self) -> None:
        assert classify_command_risk("eslint src/") == CommandRiskLevel.SAFE

    def test_ruff_safe(self) -> None:
        assert classify_command_risk("ruff check .") == CommandRiskLevel.SAFE

    def test_mypy_safe(self) -> None:
        assert classify_command_risk("mypy src/") == CommandRiskLevel.SAFE

    def test_pyright_safe(self) -> None:
        assert classify_command_risk("pyright") == CommandRiskLevel.SAFE

    def test_tsc_safe(self) -> None:
        assert classify_command_risk("tsc --noEmit") == CommandRiskLevel.SAFE

    def test_make_safe(self) -> None:
        assert classify_command_risk("make build") == CommandRiskLevel.SAFE

    def test_cmake_safe(self) -> None:
        assert classify_command_risk("cmake ..") == CommandRiskLevel.SAFE

    def test_jq_safe(self) -> None:
        assert classify_command_risk("jq .key file.json") == CommandRiskLevel.SAFE

    def test_prettier_safe(self) -> None:
        assert classify_command_risk("prettier --check src/") == CommandRiskLevel.SAFE

    def test_shellcheck_safe(self) -> None:
        assert classify_command_risk("shellcheck script.sh") == CommandRiskLevel.SAFE

    def test_black_safe(self) -> None:
        assert classify_command_risk("black --check .") == CommandRiskLevel.SAFE

    def test_isort_safe(self) -> None:
        assert classify_command_risk("isort --check-only .") == CommandRiskLevel.SAFE
