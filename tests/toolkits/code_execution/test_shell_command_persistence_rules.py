"""Persistence-target rules of the shell command analyzer.

SSH access files and the cron table are the persistence mechanisms a shell
command can plant without touching the shell startup files that were already
covered. The ``injection`` category is reserved for shell-syntax vectors so
callers vetting human-authored commands can waive it without ever waiving
control-character smuggling.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.code_execution.security.shell_command_analyzer import (
    ThreatLevel,
    analyze_command,
)


def _details(command: str, level: ThreatLevel) -> list[str]:
    return [threat.detail for threat in analyze_command(command) if threat.level == level]


class TestSshAccessFileWrites:
    @pytest.mark.parametrize(
        "command",
        [
            "echo ssh-rsa AAAA >> ~/.ssh/authorized_keys",
            "echo ssh-rsa AAAA > /home/dev/.ssh/authorized_keys",
            'cat key.pub >> "$HOME/.ssh/authorized_keys"',
            "echo ssh-rsa AAAA | tee -a ~/.ssh/authorized_keys",
            "echo x >> ~/.ssh/authorized_keys2",
            "echo 'Host *' > ~/.ssh/config",
        ],
    )
    def test_writes_are_blocked(self, command: str) -> None:
        assert "Modifying SSH access files" in _details(command, ThreatLevel.BLOCK)

    @pytest.mark.parametrize(
        "command",
        [
            "cat ~/.ssh/authorized_keys",
            "ssh -F ~/.ssh/config build-host",
            "grep -c ssh-rsa ~/.ssh/authorized_keys > /tmp/key-count",
            "echo done > /dev/null && cat ~/.ssh/config",
            "ls -la ~/.ssh/",
        ],
    )
    def test_reads_and_unrelated_redirects_stay_clean(self, command: str) -> None:
        assert analyze_command(command) == ()


class TestCrontabModification:
    @pytest.mark.parametrize(
        "command",
        [
            "crontab -e",
            "crontab -r",
            "crontab -i",
            "crontab -",
            "echo '* * * * * job' | crontab -",
            "crontab mycron",
        ],
    )
    def test_modifications_escalate(self, command: str) -> None:
        assert "Cron table modification (persistence)" in _details(command, ThreatLevel.ESCALATE)
        assert _details(command, ThreatLevel.BLOCK) == []

    @pytest.mark.parametrize("command", ["crontab -l", "crontab -l | grep backup", 'echo "crontab"'])
    def test_listing_and_mentions_stay_clean(self, command: str) -> None:
        assert analyze_command(command) == ()


class TestInjectionCategorySplit:
    @pytest.mark.parametrize(("char", "detail"), [("\r", "embedded carriage return"), ("\x00", "null byte")])
    def test_control_characters_are_binary_injection(self, char: str, detail: str) -> None:
        threats = [threat for threat in analyze_command(f"echo a{char}b") if threat.detail == detail]

        assert [(threat.level, threat.category) for threat in threats] == [(ThreatLevel.BLOCK, "binary_injection")]

    @pytest.mark.parametrize(
        ("command", "detail"),
        [
            ("echo $(whoami)", "$() command substitution"),
            ("echo `whoami`", "backtick command substitution"),
            ("echo ${HOME}", "${} variable expansion"),
            ("echo a; echo b", "semicolon command chaining"),
        ],
    )
    def test_shell_syntax_vectors_keep_injection_category(self, command: str, detail: str) -> None:
        categories = {threat.category for threat in analyze_command(command) if detail in threat.detail}

        assert categories == {"injection"}
