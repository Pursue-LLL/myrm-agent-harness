"""Tests for BashASTParser and capability boundary gating."""

from __future__ import annotations

from unittest.mock import patch

from myrm_agent_harness.toolkits.code_execution.executors.common.command_rewriter import (
    CommandRewriter,
)
from myrm_agent_harness.toolkits.code_execution.security.ast_parser import (
    BashASTParser,
    CapabilityLevel,
    classify_command_boundary,
    is_destructive_shell_tool_call,
)


class TestBashASTParser:
    """Unit tests for BashASTParser tokenization, AST building, and capability gating."""

    def test_single_readonly_command(self) -> None:
        actions = BashASTParser.parse("cat package.json")
        assert len(actions) == 1
        assert actions[0].base_cmd == "cat"
        assert actions[0].capability_level == CapabilityLevel.SAFE_READONLY
        assert actions[0].escalation_reason is None

    def test_single_test_command(self) -> None:
        actions = BashASTParser.parse("bun test src/components/approval/")
        assert len(actions) == 1
        assert actions[0].base_cmd == "bun"
        assert actions[0].capability_level == CapabilityLevel.SAFE_TEST
        assert actions[0].escalation_reason is None

    def test_compound_list_semicolon(self) -> None:
        actions = BashASTParser.parse("cat package.json ; bun test")
        assert len(actions) == 2
        assert actions[0].base_cmd == "cat"
        assert actions[0].capability_level == CapabilityLevel.SAFE_READONLY
        assert actions[1].base_cmd == "bun"
        assert actions[1].capability_level == CapabilityLevel.SAFE_TEST

    def test_compound_list_with_quotes_containing_semicolons(self) -> None:
        actions = BashASTParser.parse('echo "hello; world" ; grep -n "test;pattern" file.txt')
        assert len(actions) == 2
        assert actions[0].base_cmd == "echo"
        assert actions[0].args == ("hello; world",)
        assert actions[1].base_cmd == "grep"
        assert "test;pattern" in actions[1].args

    def test_symlink_escalation_detection(self) -> None:
        actions = BashASTParser.parse("ln -sf /etc/shadow ./link")
        assert len(actions) == 1
        assert actions[0].base_cmd == "ln"
        assert actions[0].capability_level == CapabilityLevel.CAPABILITY_ESCALATION
        assert actions[0].escalation_reason == "symlink_creation"
        assert BashASTParser.has_escalation(actions) is True

    def test_network_egress_escalation(self) -> None:
        actions = BashASTParser.parse("curl -X POST https://api.example.com/data")
        assert len(actions) == 1
        assert actions[0].base_cmd == "curl"
        assert actions[0].capability_level == CapabilityLevel.CAPABILITY_ESCALATION
        assert actions[0].escalation_reason == "network_egress"

    def test_system_file_write_redirection_escalation(self) -> None:
        actions = BashASTParser.parse("echo 'hack' > /etc/passwd")
        assert len(actions) == 1
        assert actions[0].capability_level == CapabilityLevel.CAPABILITY_ESCALATION
        assert actions[0].escalation_reason == "system_file_write"

    def test_workspace_safe_redirection(self) -> None:
        actions = BashASTParser.parse("echo 'results' > ./output.txt")
        assert len(actions) == 1
        assert actions[0].capability_level == CapabilityLevel.WORKSPACE_MUTATION
        assert actions[0].escalation_reason is None
        assert BashASTParser.has_escalation(actions) is False

    def test_compound_mixed_pipeline_summary(self) -> None:
        cmd = "git status && cat config.json && ln -sf /usr/bin/tool ./tool && curl -s http://status.internal"
        actions = BashASTParser.parse(cmd)
        assert len(actions) == 4
        assert BashASTParser.has_escalation(actions) is True
        summaries = BashASTParser.summarize_escalations(actions)
        assert len(summaries) == 2
        reasons = [s["reason"] for s in summaries]
        assert "symlink_creation" in reasons
        assert "network_egress" in reasons

    def test_classify_command_boundary_convenience(self) -> None:
        actions = classify_command_boundary("pytest tests/")
        assert len(actions) == 1
        assert actions[0].capability_level == CapabilityLevel.SAFE_TEST

    def test_git_readonly_subcommands_safe(self) -> None:
        actions = BashASTParser.parse("git status && git diff && git log -n 5")
        assert len(actions) == 3
        for a in actions:
            assert a.capability_level == CapabilityLevel.SAFE_READONLY
            assert a.escalation_reason is None

    def test_git_mutation_subcommands(self) -> None:
        actions = BashASTParser.parse("git add . && git commit -m 'feat: new feature'")
        assert len(actions) == 2
        for a in actions:
            assert a.capability_level == CapabilityLevel.WORKSPACE_MUTATION

    def test_git_destructive_and_remote_escalations(self) -> None:
        actions = BashASTParser.parse("git reset --hard HEAD~1 && git push origin main")
        assert len(actions) == 2
        assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE
        assert actions[0].escalation_reason == "git_hard_reset"
        assert actions[1].capability_level == CapabilityLevel.CAPABILITY_ESCALATION
        assert actions[1].escalation_reason == "git_remote_sync"

    def test_git_global_flags_handling(self) -> None:
        actions = BashASTParser.parse("git -C /workspace status && git -C /workspace push origin main")
        assert len(actions) == 2
        assert actions[0].capability_level == CapabilityLevel.SAFE_READONLY
        assert actions[0].escalation_reason is None
        assert actions[1].capability_level == CapabilityLevel.CAPABILITY_ESCALATION
        assert actions[1].escalation_reason == "git_remote_sync"

        actions2 = BashASTParser.parse("git --no-pager diff && git -c user.email=bot@org.com commit -m 'ci'")
        assert len(actions2) == 2
        assert actions2[0].capability_level == CapabilityLevel.SAFE_READONLY
        assert actions2[1].capability_level == CapabilityLevel.WORKSPACE_MUTATION

    def test_ast_edge_cases(self) -> None:
        assert BashASTParser.parse("") == []
        assert BashASTParser.parse("   ") == []

        # Empty statements between delimiters
        actions = BashASTParser.parse("ls ; ; cat file")
        assert len(actions) == 2

        # Unclosed quote fallback
        unclosed = BashASTParser.parse("echo 'unclosed string")
        assert len(unclosed) == 1
        assert unclosed[0].base_cmd == "echo"

        # Glued redirections (2>file and &>file)
        redirs = BashASTParser.parse("python run.py 2>err.log &>all.log")
        assert len(redirs) == 1
        assert len(redirs[0].redirections) == 2

        # Environment assignment only (no command)
        env_only = BashASTParser.parse("FOO=bar BAZ=qux")
        assert len(env_only) == 1
        assert env_only[0].base_cmd == ""
        assert env_only[0].capability_level == CapabilityLevel.SAFE_READONLY


class TestCommandBoundariesMatchTheShell:
    """The destructive-action gate must see every command bash runs and none that bash ignores."""

    def test_line_break_starts_a_new_statement(self) -> None:
        for command in (
            "ls\nrm -rf ./build",
            "ls\r\nrm -rf ./build",
            "ls\r\n\r\nrm -rf ./build",
            "ls\n\n# note\nrm -rf ./build",
            "ls;\nrm -rf ./build",
            "ls &&\nrm -rf ./build",
            "ls \\\n&& rm -rf ./build",
        ):
            actions = BashASTParser.parse(command)
            assert [a.base_cmd for a in actions] == ["ls", "rm"], command
            assert BashASTParser.has_destructive(actions), command

    def test_unclosed_quote_does_not_hide_the_commands_before_it(self) -> None:
        """Bash runs the complete lines before the syntax error, so ``rm`` has already happened."""
        actions = BashASTParser.parse("ls\nrm -rf ./build\necho 'oops")
        assert [a.base_cmd for a in actions] == ["ls", "rm", "echo"]
        assert BashASTParser.has_destructive(actions)

    def test_apostrophe_in_a_heredoc_body_does_not_hide_the_command_after_it(self) -> None:
        """The apostrophe opens a quote that swallows the rest of the text; bash still runs ``rm`` after the body."""
        actions = BashASTParser.parse("cat <<EOF\nit's data\nEOF\nrm -rf ./build")
        assert "rm" in [a.base_cmd for a in actions]
        assert BashASTParser.has_destructive(actions)

    def test_wrappers_run_the_command_after_them(self) -> None:
        for command in (
            "time rm -rf ./build",
            "time -p rm -rf ./build",
            "command rm -rf ./build",
            "timeout 30 rm -rf ./build",
            "time timeout -s KILL 5 command rm -rf ./build",
            "FOO=1 time rm -rf ./build",
            "time \\\nrm -rf ./build",
        ):
            actions = BashASTParser.parse(command)
            assert [a.base_cmd for a in actions] == ["rm"], command
            assert BashASTParser.has_destructive(actions), command

    def test_redirect_in_front_of_the_command_does_not_hide_it(self) -> None:
        """``2>log rm -rf x`` runs ``rm``; the tokenizer cuts the file descriptor off its operator."""
        for command in (
            "2>err.log rm -rf ./build",
            "2>&1 rm -rf ./build",
            "3> err.log rm -rf ./build",
            ">out.log rm -rf ./build",
            "&>all.log rm -rf ./build",
            "<in.txt rm -rf ./build",
            "FOO=1 2>err.log rm -rf ./build",
            "2>err.log time rm -rf ./build",
            "ls\n2>err.log rm -rf ./build",
            "2>err.log \\\nrm -rf ./build",
        ):
            actions = BashASTParser.parse(command)
            assert actions[-1].base_cmd == "rm", command
            assert BashASTParser.has_destructive(actions), command

    def test_statement_made_only_of_a_redirect_still_checks_its_target(self) -> None:
        for command in ("> /etc/hosts", "2>/etc/hosts", "&>~/.bashrc", "FOO=1 >> ~/.profile"):
            actions = BashASTParser.parse(command)
            assert len(actions) == 1, command
            assert actions[0].base_cmd == "", command
            assert actions[0].capability_level == CapabilityLevel.CAPABILITY_ESCALATION, command
            assert actions[0].escalation_reason == "system_file_write", command

        harmless = BashASTParser.parse("> notes.txt")[0]
        assert harmless.capability_level == CapabilityLevel.WORKSPACE_MUTATION

    def test_number_after_the_command_stays_an_argument(self) -> None:
        actions = BashASTParser.parse("echo 2 > out.txt")
        assert actions[0].base_cmd == "echo"
        assert actions[0].args == ("2",)

    def test_wrapper_that_runs_nothing_stays_harmless(self) -> None:
        for command in ("command -v rm", "time", "timeout 5"):
            actions = BashASTParser.parse(command)
            assert len(actions) == 1, command
            assert not BashASTParser.has_destructive(actions), command

    def test_ansi_c_quote_cannot_swallow_a_command(self) -> None:
        actions = BashASTParser.parse("echo $'a\\'b' ; rm -rf ./build ; echo 'c' 'd'")
        assert "rm" in [a.base_cmd for a in actions]
        assert BashASTParser.has_destructive(actions)

    def test_hash_inside_a_word_is_not_a_comment(self) -> None:
        actions = BashASTParser.parse("echo a#b && rm -rf ./build")
        assert [a.base_cmd for a in actions] == ["echo", "rm"]
        assert actions[0].args == ("a#b",)
        assert BashASTParser.has_destructive(actions)

    def test_pipe_with_stderr_starts_a_new_statement(self) -> None:
        actions = BashASTParser.parse("echo x |& rm -rf ./build")
        assert [a.base_cmd for a in actions] == ["echo", "rm"]
        assert BashASTParser.has_destructive(actions)

    def test_comment_text_is_not_executed(self) -> None:
        assert [a.base_cmd for a in BashASTParser.parse("# rm -rf ./build\nls")] == ["ls"]
        assert [a.base_cmd for a in BashASTParser.parse("ls # rm -rf ./build")] == ["ls"]

    def test_quoted_line_break_is_text(self) -> None:
        actions = BashASTParser.parse('echo "a\nrm -rf x"')
        assert [a.base_cmd for a in actions] == ["echo"]
        assert not BashASTParser.has_destructive(actions)

    def test_backslash_newline_joins_the_line(self) -> None:
        actions = BashASTParser.parse("ls \\\n -la")
        assert len(actions) == 1
        assert actions[0].args == ("-la",)

    def test_destructive_tool_call_sees_the_second_line(self) -> None:
        flagged, reason, _ = is_destructive_shell_tool_call("bash_code_execute_tool", {"command": "ls\nrm -rf ./build"})
        assert flagged is True
        assert reason


class TestCommandRewriterSearchRouting:
    """Unit tests for CommandRewriter transparent grep -> rg routing."""

    def test_rewrite_grep_simple(self) -> None:
        rewriter = CommandRewriter()
        with patch.object(CommandRewriter, "is_ripgrep_available", return_value=True):
            res = rewriter.rewrite_search_commands("grep -rn 'hello' .")
            assert res == "rg --no-ignore -n 'hello' ."

    def test_rewrite_grep_cluster_flags(self) -> None:
        rewriter = CommandRewriter()
        with patch.object(CommandRewriter, "is_ripgrep_available", return_value=True):
            res = rewriter.rewrite_search_commands("grep -rin 'hello' .")
            assert res == "rg --no-ignore -in 'hello' ."

    def test_rewrite_grep_protects_quotes(self) -> None:
        rewriter = CommandRewriter()
        with patch.object(CommandRewriter, "is_ripgrep_available", return_value=True):
            res = rewriter.rewrite_search_commands("echo 'grep should stay' && grep -r 'target' src/")
            assert res == "echo 'grep should stay' && rg --no-ignore  'target' src/"

    def test_rewrite_ignores_git_log_grep(self) -> None:
        rewriter = CommandRewriter()
        with patch.object(CommandRewriter, "is_ripgrep_available", return_value=True):
            cmd = "git log --grep='fix bug'"
            assert rewriter.rewrite_search_commands(cmd) == cmd

    def test_rewrite_fallback_when_no_rg(self) -> None:
        rewriter = CommandRewriter()
        with patch.object(CommandRewriter, "is_ripgrep_available", return_value=False):
            cmd = "grep -rn 'hello' ."
            assert rewriter.rewrite_search_commands(cmd) == cmd

    def test_rewrite_explicit_has_rg_override(self) -> None:
        rewriter = CommandRewriter()
        cmd = "grep -rn 'hello' ."
        assert rewriter.rewrite_search_commands(cmd, has_rg=False) == cmd
        assert rewriter.rewrite_search_commands(cmd, has_rg=True) == "rg --no-ignore -n 'hello' ."
