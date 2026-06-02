"""Command Classifier单元测试"""

from myrm_agent_harness.agent.meta_tools.bash.command_classifier import CommandClassifier, CommandType, RiskLevel


class TestCommandClassifier:
    """测试命令分类器"""

    def test_read_commands(self):
        """测试只读命令分类"""
        commands = [
            "cat file.txt",
            "head -n 10 file.txt",
            "tail -f log.txt",
            "less file.txt",
            "ls -la",
            "pwd",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.READ
            assert risk_level == RiskLevel.LOW

    def test_search_commands(self):
        """测试搜索命令分类"""
        commands = [
            "grep pattern file.txt",
            "rg 'search' .",
            "find . -name '*.py'",
            "which python",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.SEARCH
            assert risk_level == RiskLevel.LOW

    def test_write_commands(self):
        """测试写入命令分类"""
        commands = [
            "cp file1.txt file2.txt",
            "mv old.txt new.txt",
            "mkdir newdir",
            "touch newfile.txt",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.WRITE
            assert risk_level == RiskLevel.MEDIUM

    def test_dangerous_commands(self):
        """测试危险命令分类"""
        commands = [
            "rm -rf /tmp/test",
            "dd if=/dev/zero of=/dev/sda",
            "mkfs.ext4 /dev/sdb1",
            "chmod 777 file.txt",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.DANGEROUS
            assert risk_level == RiskLevel.HIGH

    def test_network_commands(self):
        """测试网络命令分类"""
        commands = [
            "curl https://example.com",
            "wget https://example.com/file.zip",
            "ssh user@host",
            "scp file.txt user@host:/path/",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.NETWORK
            assert risk_level == RiskLevel.MEDIUM

    def test_git_commands(self):
        """测试Git命令分类"""
        commands = [
            "git status",
            "git commit -m 'message'",
            "git push origin main",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.GIT
            assert risk_level == RiskLevel.MEDIUM

    def test_python_commands(self):
        """测试Python命令分类"""
        commands = [
            "python script.py",
            "python3 -c 'print(123)'",
            "pip install package",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.PYTHON
            assert risk_level == RiskLevel.LOW

    def test_skill_commands(self):
        """测试技能调用分类"""
        commands = [
            "python -c 'from skills.search import search'",
            "python -c 'import skills.weather'",
        ]
        for cmd in commands:
            cmd_type, risk_level = CommandClassifier.classify(cmd)
            assert cmd_type == CommandType.SKILL
            assert risk_level == RiskLevel.LOW

    def test_env_var_prefix(self):
        """测试环境变量前缀"""
        cmd = "VAR=value python script.py"
        cmd_type, risk_level = CommandClassifier.classify(cmd)
        assert cmd_type == CommandType.PYTHON
        assert risk_level == RiskLevel.LOW

    def test_empty_command(self):
        """测试空命令"""
        cmd_type, risk_level = CommandClassifier.classify("")
        assert cmd_type == CommandType.UNKNOWN
        assert risk_level == RiskLevel.LOW

    def test_unknown_command(self):
        """测试未知命令"""
        cmd = "someunknowncommand arg1 arg2"
        cmd_type, risk_level = CommandClassifier.classify(cmd)
        assert cmd_type == CommandType.UNKNOWN
        assert risk_level == RiskLevel.LOW
