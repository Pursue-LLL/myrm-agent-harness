"""Tests for flag-level command validation (git subcommand whitelist engine)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
    CommandRiskLevel,
    classify_command_risk,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs import (
    GIT_SAFE_SUBCOMMANDS,
    FlagArgType,
)

# ---------------------------------------------------------------------------
# Git read-only commands — auto-allowed
# ---------------------------------------------------------------------------


class TestGitReadOnlyAutoAllowed:
    """Git commands that should be classified as SAFE."""

    def test_git_status(self) -> None:
        assert classify_command_risk("git status") == CommandRiskLevel.SAFE

    def test_git_status_short(self) -> None:
        assert classify_command_risk("git status -s") == CommandRiskLevel.SAFE

    def test_git_status_porcelain_branch(self) -> None:
        assert classify_command_risk("git status --porcelain --branch") == CommandRiskLevel.SAFE

    def test_git_diff(self) -> None:
        assert classify_command_risk("git diff") == CommandRiskLevel.SAFE

    def test_git_diff_cached(self) -> None:
        assert classify_command_risk("git diff --cached") == CommandRiskLevel.SAFE

    def test_git_diff_staged(self) -> None:
        assert classify_command_risk("git diff --staged") == CommandRiskLevel.SAFE

    def test_git_diff_stat(self) -> None:
        assert classify_command_risk("git diff --stat") == CommandRiskLevel.SAFE

    def test_git_diff_with_path(self) -> None:
        assert classify_command_risk("git diff src/main.py") == CommandRiskLevel.SAFE

    def test_git_diff_between_refs(self) -> None:
        assert classify_command_risk("git diff HEAD~3 HEAD") == CommandRiskLevel.SAFE

    def test_git_diff_name_only(self) -> None:
        assert classify_command_risk("git diff --name-only HEAD~1") == CommandRiskLevel.SAFE

    def test_git_diff_algorithm(self) -> None:
        assert classify_command_risk("git diff --diff-algorithm=histogram") == CommandRiskLevel.SAFE

    def test_git_log(self) -> None:
        assert classify_command_risk("git log") == CommandRiskLevel.SAFE

    def test_git_log_oneline(self) -> None:
        assert classify_command_risk("git log --oneline") == CommandRiskLevel.SAFE

    def test_git_log_graph(self) -> None:
        assert classify_command_risk("git log --oneline --graph --all") == CommandRiskLevel.SAFE

    def test_git_log_n_flag(self) -> None:
        assert classify_command_risk("git log -n 10") == CommandRiskLevel.SAFE

    def test_git_log_numeric_shorthand(self) -> None:
        assert classify_command_risk("git log -5") == CommandRiskLevel.SAFE

    def test_git_log_pretty_format(self) -> None:
        assert classify_command_risk("git log --pretty=format:%H") == CommandRiskLevel.SAFE

    def test_git_log_author_filter(self) -> None:
        assert classify_command_risk("git log --author=john") == CommandRiskLevel.SAFE

    def test_git_log_since_date(self) -> None:
        assert classify_command_risk("git log --since=2024-01-01") == CommandRiskLevel.SAFE

    def test_git_log_pickaxe(self) -> None:
        assert classify_command_risk("git log -S search_term") == CommandRiskLevel.SAFE

    def test_git_show(self) -> None:
        assert classify_command_risk("git show HEAD") == CommandRiskLevel.SAFE

    def test_git_show_stat(self) -> None:
        assert classify_command_risk("git show --stat HEAD~2") == CommandRiskLevel.SAFE

    def test_git_show_format(self) -> None:
        assert classify_command_risk("git show --format=%B HEAD") == CommandRiskLevel.SAFE

    def test_git_blame(self) -> None:
        assert classify_command_risk("git blame src/main.py") == CommandRiskLevel.SAFE

    def test_git_blame_line_range(self) -> None:
        assert classify_command_risk("git blame -L 10,20 src/main.py") == CommandRiskLevel.SAFE

    def test_git_blame_porcelain(self) -> None:
        assert classify_command_risk("git blame --porcelain src/main.py") == CommandRiskLevel.SAFE

    def test_git_branch_list(self) -> None:
        assert classify_command_risk("git branch") == CommandRiskLevel.SAFE

    def test_git_branch_all(self) -> None:
        assert classify_command_risk("git branch -a") == CommandRiskLevel.SAFE

    def test_git_branch_verbose(self) -> None:
        assert classify_command_risk("git branch -vv") == CommandRiskLevel.SAFE

    def test_git_branch_list_flag(self) -> None:
        assert classify_command_risk("git branch --list main*") == CommandRiskLevel.SAFE

    def test_git_tag_list(self) -> None:
        assert classify_command_risk("git tag") == CommandRiskLevel.SAFE

    def test_git_tag_list_explicit(self) -> None:
        assert classify_command_risk("git tag -l") == CommandRiskLevel.SAFE

    def test_git_tag_list_pattern(self) -> None:
        assert classify_command_risk("git tag -l v1.*") == CommandRiskLevel.SAFE

    def test_git_tag_contains(self) -> None:
        assert classify_command_risk("git tag --contains HEAD") == CommandRiskLevel.SAFE

    def test_git_ls_files(self) -> None:
        assert classify_command_risk("git ls-files") == CommandRiskLevel.SAFE

    def test_git_ls_files_modified(self) -> None:
        assert classify_command_risk("git ls-files -m") == CommandRiskLevel.SAFE

    def test_git_rev_parse(self) -> None:
        assert classify_command_risk("git rev-parse HEAD") == CommandRiskLevel.SAFE

    def test_git_rev_parse_show_toplevel(self) -> None:
        assert classify_command_risk("git rev-parse --show-toplevel") == CommandRiskLevel.SAFE

    def test_git_rev_parse_abbrev_ref(self) -> None:
        assert classify_command_risk("git rev-parse --abbrev-ref HEAD") == CommandRiskLevel.SAFE

    def test_git_describe(self) -> None:
        assert classify_command_risk("git describe --tags --always") == CommandRiskLevel.SAFE

    def test_git_shortlog(self) -> None:
        assert classify_command_risk("git shortlog -sn") == CommandRiskLevel.SAFE

    def test_git_cat_file(self) -> None:
        assert classify_command_risk("git cat-file -p HEAD") == CommandRiskLevel.SAFE

    def test_git_merge_base(self) -> None:
        assert classify_command_risk("git merge-base main feature") == CommandRiskLevel.SAFE

    def test_git_merge_base_is_ancestor(self) -> None:
        assert classify_command_risk("git merge-base --is-ancestor abc def") == CommandRiskLevel.SAFE

    def test_git_rev_list(self) -> None:
        assert classify_command_risk("git rev-list --count HEAD") == CommandRiskLevel.SAFE

    def test_git_for_each_ref(self) -> None:
        assert classify_command_risk("git for-each-ref --format=%(refname)") == CommandRiskLevel.SAFE

    def test_git_grep(self) -> None:
        assert classify_command_risk("git grep -n pattern") == CommandRiskLevel.SAFE

    def test_git_grep_context(self) -> None:
        assert classify_command_risk("git grep -C 3 -i TODO") == CommandRiskLevel.SAFE

    def test_git_reflog(self) -> None:
        assert classify_command_risk("git reflog") == CommandRiskLevel.SAFE

    def test_git_reflog_show(self) -> None:
        assert classify_command_risk("git reflog show") == CommandRiskLevel.SAFE

    def test_git_stash_list(self) -> None:
        assert classify_command_risk("git stash list") == CommandRiskLevel.SAFE

    def test_git_stash_show(self) -> None:
        assert classify_command_risk("git stash show") == CommandRiskLevel.SAFE

    def test_git_stash_show_patch(self) -> None:
        assert classify_command_risk("git stash show -p") == CommandRiskLevel.SAFE

    def test_git_worktree_list(self) -> None:
        assert classify_command_risk("git worktree list") == CommandRiskLevel.SAFE

    def test_git_remote(self) -> None:
        assert classify_command_risk("git remote") == CommandRiskLevel.SAFE

    def test_git_remote_verbose(self) -> None:
        assert classify_command_risk("git remote -v") == CommandRiskLevel.SAFE

    def test_git_remote_show_origin(self) -> None:
        assert classify_command_risk("git remote show origin") == CommandRiskLevel.SAFE

    def test_git_ls_remote(self) -> None:
        assert classify_command_risk("git ls-remote") == CommandRiskLevel.SAFE

    def test_git_config_get(self) -> None:
        assert classify_command_risk("git config --get user.email") == CommandRiskLevel.SAFE


# ---------------------------------------------------------------------------
# Git write/dangerous commands — must remain UNKNOWN
# ---------------------------------------------------------------------------


class TestGitDangerousCommands:
    """Git commands that should NOT be classified as SAFE."""

    def test_git_push(self) -> None:
        assert classify_command_risk("git push") == CommandRiskLevel.UNKNOWN

    def test_git_push_origin_main(self) -> None:
        assert classify_command_risk("git push origin main") == CommandRiskLevel.UNKNOWN

    def test_git_commit(self) -> None:
        assert classify_command_risk("git commit -m msg") == CommandRiskLevel.UNKNOWN

    def test_git_add(self) -> None:
        assert classify_command_risk("git add .") == CommandRiskLevel.UNKNOWN

    def test_git_checkout(self) -> None:
        assert classify_command_risk("git checkout main") == CommandRiskLevel.UNKNOWN

    def test_git_merge(self) -> None:
        assert classify_command_risk("git merge feature") == CommandRiskLevel.UNKNOWN

    def test_git_rebase(self) -> None:
        assert classify_command_risk("git rebase main") == CommandRiskLevel.UNKNOWN

    def test_git_reset(self) -> None:
        assert classify_command_risk("git reset --hard HEAD~1") == CommandRiskLevel.UNKNOWN

    def test_git_clean(self) -> None:
        assert classify_command_risk("git clean -fd") == CommandRiskLevel.UNKNOWN

    def test_git_stash_bare(self) -> None:
        assert classify_command_risk("git stash") == CommandRiskLevel.UNKNOWN

    def test_git_stash_push(self) -> None:
        assert classify_command_risk("git stash push") == CommandRiskLevel.UNKNOWN

    def test_git_stash_pop(self) -> None:
        assert classify_command_risk("git stash pop") == CommandRiskLevel.UNKNOWN

    def test_git_stash_drop(self) -> None:
        assert classify_command_risk("git stash drop") == CommandRiskLevel.UNKNOWN

    def test_git_pull(self) -> None:
        assert classify_command_risk("git pull") == CommandRiskLevel.UNKNOWN

    def test_git_fetch(self) -> None:
        assert classify_command_risk("git fetch") == CommandRiskLevel.UNKNOWN

    def test_git_switch(self) -> None:
        assert classify_command_risk("git switch feature") == CommandRiskLevel.UNKNOWN

    def test_git_worktree_add(self) -> None:
        assert classify_command_risk("git worktree add /tmp/wt") == CommandRiskLevel.UNKNOWN

    def test_git_config_set(self) -> None:
        assert classify_command_risk("git config user.email foo@bar") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Security: branch/tag creation detection
# ---------------------------------------------------------------------------


class TestGitBranchTagCreation:
    """Positional args that indicate write operations must be blocked."""

    def test_git_branch_create(self) -> None:
        assert classify_command_risk("git branch newbranch") == CommandRiskLevel.UNKNOWN

    def test_git_branch_create_from_ref(self) -> None:
        assert classify_command_risk("git branch newbranch HEAD~3") == CommandRiskLevel.UNKNOWN

    def test_git_tag_create(self) -> None:
        assert classify_command_risk("git tag v1.0") == CommandRiskLevel.UNKNOWN

    def test_git_tag_create_at_ref(self) -> None:
        assert classify_command_risk("git tag v1.0 abc123") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Security: reflog write subcommands
# ---------------------------------------------------------------------------


class TestGitReflogSecurity:
    """Reflog expire/delete must be blocked."""

    def test_reflog_expire(self) -> None:
        assert classify_command_risk("git reflog expire") == CommandRiskLevel.UNKNOWN

    def test_reflog_delete(self) -> None:
        assert classify_command_risk("git reflog delete") == CommandRiskLevel.UNKNOWN

    def test_reflog_exists(self) -> None:
        assert classify_command_risk("git reflog exists") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Security: unknown flags rejected
# ---------------------------------------------------------------------------


class TestGitUnknownFlagRejection:
    """Unknown flags should cause UNKNOWN classification."""

    def test_diff_unknown_flag(self) -> None:
        assert classify_command_risk("git diff --output=pwned.txt") == CommandRiskLevel.UNKNOWN

    def test_log_unknown_flag(self) -> None:
        assert classify_command_risk("git log --exec=rm") == CommandRiskLevel.UNKNOWN

    def test_status_unknown_flag(self) -> None:
        assert classify_command_risk("git status --unknown") == CommandRiskLevel.UNKNOWN

    def test_branch_delete_flag(self) -> None:
        assert classify_command_risk("git branch -d main") == CommandRiskLevel.UNKNOWN

    def test_branch_force_delete_flag(self) -> None:
        assert classify_command_risk("git branch -D main") == CommandRiskLevel.UNKNOWN

    def test_tag_delete_flag(self) -> None:
        assert classify_command_risk("git tag -d v1.0") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Security: flag-with-equals parsing
# ---------------------------------------------------------------------------


class TestFlagEqualsFormat:
    """Flags with --flag=value format."""

    def test_diff_algorithm_equals(self) -> None:
        assert classify_command_risk("git diff --diff-algorithm=patience") == CommandRiskLevel.SAFE

    def test_log_max_count_equals(self) -> None:
        assert classify_command_risk("git log --max-count=5") == CommandRiskLevel.SAFE

    def test_none_type_flag_with_equals_rejected(self) -> None:
        assert classify_command_risk("git diff --cached=true") == CommandRiskLevel.UNKNOWN

    def test_number_flag_with_string_value_rejected(self) -> None:
        assert classify_command_risk("git log --max-count=abc") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Security: short flag bundles
# ---------------------------------------------------------------------------


class TestShortFlagBundle:
    """Bundled short flags like -sn for git shortlog."""

    def test_shortlog_sn_bundle(self) -> None:
        assert classify_command_risk("git shortlog -sn") == CommandRiskLevel.SAFE

    def test_shortlog_sne_bundle(self) -> None:
        assert classify_command_risk("git shortlog -sne") == CommandRiskLevel.SAFE

    def test_status_sb_bundle(self) -> None:
        assert classify_command_risk("git status -sb") == CommandRiskLevel.SAFE

    def test_unknown_char_in_bundle_rejected(self) -> None:
        assert classify_command_risk("git status -sz") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Security: remote show requires valid name
# ---------------------------------------------------------------------------


class TestGitRemoteShow:
    """git remote show requires exactly one safe remote name."""

    def test_remote_show_valid_name(self) -> None:
        assert classify_command_risk("git remote show origin") == CommandRiskLevel.SAFE

    def test_remote_show_upstream(self) -> None:
        assert classify_command_risk("git remote show upstream") == CommandRiskLevel.SAFE

    def test_remote_show_no_name(self) -> None:
        # No remote name = git shows help/error, still read-only
        assert classify_command_risk("git remote show") == CommandRiskLevel.SAFE

    def test_remote_show_multiple_names(self) -> None:
        assert classify_command_risk("git remote show origin upstream") == CommandRiskLevel.UNKNOWN

    def test_remote_show_url_injection(self) -> None:
        assert classify_command_risk("git remote show https://evil.com") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Git in pipeline — mixed with simple commands
# ---------------------------------------------------------------------------


class TestGitInPipeline:
    """Git commands piped with simple safe commands."""

    def test_git_log_pipe_grep(self) -> None:
        assert classify_command_risk("git log --oneline | grep fix") == CommandRiskLevel.SAFE

    def test_git_diff_pipe_wc(self) -> None:
        assert classify_command_risk("git diff --name-only | wc -l") == CommandRiskLevel.SAFE

    def test_git_branch_pipe_sort(self) -> None:
        assert classify_command_risk("git branch -a | sort") == CommandRiskLevel.SAFE

    def test_git_unsafe_pipe_safe(self) -> None:
        assert classify_command_risk("git push | cat") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# POSIX -- handling
# ---------------------------------------------------------------------------


class TestDoubleDash:
    """POSIX -- end-of-options handling."""

    def test_git_diff_double_dash_file(self) -> None:
        assert classify_command_risk("git diff -- src/main.py") == CommandRiskLevel.SAFE

    def test_git_log_double_dash_path(self) -> None:
        assert classify_command_risk("git log -- path/to/file") == CommandRiskLevel.SAFE


# ---------------------------------------------------------------------------
# Coverage: all git subcommand configs have at least one SAFE test
# ---------------------------------------------------------------------------


class TestGitSubcommandCoverage:
    """Ensure every configured subcommand is reachable as SAFE."""

    @pytest.mark.parametrize("subcmd", sorted(GIT_SAFE_SUBCOMMANDS.keys()))
    def test_bare_subcommand_or_with_flag(self, subcmd: str) -> None:
        config = GIT_SAFE_SUBCOMMANDS[subcmd]
        cmd = f"git {subcmd}"
        if config.is_positional_dangerous is not None:
            first_flag = next(iter(config.safe_flags), None)
            if first_flag:
                arg_type = config.safe_flags[first_flag]
                if arg_type == FlagArgType.NONE:
                    cmd = f"git {subcmd} {first_flag}"
                elif arg_type == FlagArgType.NUMBER:
                    cmd = f"git {subcmd} {first_flag} 1"
                else:
                    cmd = f"git {subcmd} {first_flag} value"
        result = classify_command_risk(cmd)
        assert result == CommandRiskLevel.SAFE, f"git {subcmd} should be SAFE but got {result} with command: {cmd}"


# ---------------------------------------------------------------------------
# Existing simple command tests still pass
# ---------------------------------------------------------------------------


class TestSimpleCommandsStillWork:
    """Verify simple SAFE_COMMANDS classification is not broken."""

    def test_simple_ls(self) -> None:
        assert classify_command_risk("ls -la") == CommandRiskLevel.SAFE

    def test_simple_cat(self) -> None:
        assert classify_command_risk("cat file.txt") == CommandRiskLevel.SAFE

    def test_simple_grep(self) -> None:
        assert classify_command_risk("grep pattern file") == CommandRiskLevel.SAFE

    def test_pipeline_safe(self) -> None:
        assert classify_command_risk("cat file | sort | uniq") == CommandRiskLevel.SAFE

    def test_rm_still_unknown(self) -> None:
        assert classify_command_risk("rm file") == CommandRiskLevel.UNKNOWN

    def test_redirect_still_unknown(self) -> None:
        assert classify_command_risk("echo hello > file.txt") == CommandRiskLevel.UNKNOWN


# ---------------------------------------------------------------------------
# Edge-case branch coverage
# ---------------------------------------------------------------------------


class TestFlagValidationEdgeCases:
    """Cover uncovered branches in risk_classifier and safe_command_configs."""

    def test_respects_double_dash_false(self) -> None:
        """When -- is encountered but config.respects_double_dash is False."""
        assert classify_command_risk("git status -- file.txt") == CommandRiskLevel.SAFE

    def test_flag_not_matching_flag_re(self) -> None:
        """Token starting with - but failing _FLAG_RE (e.g. '-')."""
        assert classify_command_risk("git diff -") == CommandRiskLevel.SAFE

    def test_flag_requires_value_but_missing(self) -> None:
        """Flag expecting an argument at end of tokens."""
        assert classify_command_risk("git diff --diff-algorithm") == CommandRiskLevel.UNKNOWN

    def test_flag_value_looks_like_another_flag(self) -> None:
        """Flag expecting value but next token is a flag."""
        assert classify_command_risk("git log --author --oneline") == CommandRiskLevel.UNKNOWN

    def test_flag_value_number_invalid(self) -> None:
        """NUMBER type flag receives non-numeric value."""
        assert classify_command_risk("git log -n abc") == CommandRiskLevel.UNKNOWN

    def test_flag_none_with_equals(self) -> None:
        """NONE-type flag used with =value should fail."""
        assert classify_command_risk("git status -s=foo") == CommandRiskLevel.UNKNOWN

    def test_short_flag_bundle_all_none(self) -> None:
        """Bundle of all NONE-type short flags is valid."""
        assert classify_command_risk("git shortlog -sne") == CommandRiskLevel.SAFE

    def test_short_flag_bundle_with_arg_taking_flag(self) -> None:
        """Bundle containing an unknown short flag should be UNKNOWN."""
        assert classify_command_risk("git log -nZx") == CommandRiskLevel.UNKNOWN

    def test_validate_flag_value_none_type(self) -> None:
        """Internal: _validate_flag_value with NONE returns False."""
        from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
            _validate_flag_value,
        )

        assert _validate_flag_value("anything", FlagArgType.NONE) is False

    def test_env_var_assignment_before_command(self) -> None:
        """Environment variable assignment prefix: FOO=bar git status."""
        assert classify_command_risk("FOO=bar git status") == CommandRiskLevel.SAFE

    def test_only_env_var_assignments(self) -> None:
        """Only env vars with no actual command."""
        assert classify_command_risk("FOO=bar BAZ=qux") == CommandRiskLevel.UNKNOWN

    def test_empty_base_command(self) -> None:
        """Edge: command resolves to empty base after rsplit."""
        assert classify_command_risk("/") == CommandRiskLevel.UNKNOWN

    def test_branch_contains_flag(self) -> None:
        """git branch --contains <commit> is safe (uses --contains)."""
        assert classify_command_risk("git branch --contains HEAD") == CommandRiskLevel.SAFE

    def test_branch_no_contains_flag(self) -> None:
        """git branch --no-contains <commit> is safe."""
        assert classify_command_risk("git branch --no-contains HEAD") == CommandRiskLevel.SAFE

    def test_branch_merged_flag(self) -> None:
        """git branch --merged is safe."""
        assert classify_command_risk("git branch --merged") == CommandRiskLevel.SAFE

    def test_branch_no_merged_flag(self) -> None:
        """git branch --no-merged is safe."""
        assert classify_command_risk("git branch --no-merged") == CommandRiskLevel.SAFE

    def test_branch_points_at_flag(self) -> None:
        """git branch --points-at HEAD is safe."""
        assert classify_command_risk("git branch --points-at HEAD") == CommandRiskLevel.SAFE

    def test_branch_show_current_flag(self) -> None:
        """git branch --show-current is safe."""
        assert classify_command_risk("git branch --show-current") == CommandRiskLevel.SAFE

    def test_git_numeric_shorthand(self) -> None:
        """Git numeric shorthand like -5 in git log."""
        assert classify_command_risk("git log -5") == CommandRiskLevel.SAFE

    def test_inline_value_with_equals_invalid(self) -> None:
        """Flag with =value where value validation fails for NUMBER type."""
        assert classify_command_risk("git log -n=abc") == CommandRiskLevel.UNKNOWN

    def test_reflog_expire_blocked(self) -> None:
        """git reflog expire is a write operation and should be UNKNOWN."""
        assert classify_command_risk("git reflog expire") == CommandRiskLevel.UNKNOWN

    def test_reflog_delete_blocked(self) -> None:
        """git reflog delete is a write operation and should be UNKNOWN."""
        assert classify_command_risk("git reflog delete") == CommandRiskLevel.UNKNOWN

    def test_branch_no_contains_with_positional(self) -> None:
        """git branch --no-contains HEAD main — positional + --no-contains flag."""
        assert classify_command_risk("git branch --no-contains HEAD main") == CommandRiskLevel.SAFE

    def test_branch_no_merged_with_positional(self) -> None:
        """git branch --no-merged main feature — positional + --no-merged flag."""
        assert classify_command_risk("git branch --no-merged main feature") == CommandRiskLevel.SAFE

    def test_branch_points_at_with_positional(self) -> None:
        """git branch --points-at HEAD main — positional + --points-at flag."""
        assert classify_command_risk("git branch --points-at HEAD main") == CommandRiskLevel.SAFE

    def test_branch_show_current_with_positional(self) -> None:
        """git branch --show-current foo — positional + --show-current flag."""
        assert classify_command_risk("git branch --show-current foo") == CommandRiskLevel.SAFE

    def test_flag_with_special_char_rejected(self) -> None:
        """Token like -@ that fails _FLAG_RE should make command UNKNOWN."""
        from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
            _validate_flags,
        )
        from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs import (
            SubcommandConfig,
        )

        config = SubcommandConfig(safe_flags={"-a": FlagArgType.NONE})
        assert _validate_flags(["-@"], 0, config) is False

    def test_respects_double_dash_false_config(self) -> None:
        """When config.respects_double_dash=False, -- is treated as positional."""
        from myrm_agent_harness.toolkits.code_execution.security.risk_classifier import (
            _validate_flags,
        )
        from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs import (
            SubcommandConfig,
        )

        config = SubcommandConfig(
            safe_flags={"-a": FlagArgType.NONE},
            respects_double_dash=False,
        )
        result = _validate_flags(["-a", "--", "file.txt"], 0, config)
        assert result is True
