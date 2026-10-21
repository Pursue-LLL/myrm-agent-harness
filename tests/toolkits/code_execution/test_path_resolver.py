"""路径解析器单元测试

PathResolver 不依赖 Docker，测试本地路径与容器路径的转换。
"""

from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.utils import WorkspacePathResolver


class TestPathResolver:
    """路径解析器测试"""

    def test_to_container_path(self):
        """测试本地路径 -> 容器路径"""
        local_path = Path("/Users/test/workspace_123/.claude/skills/my_skill")
        workspace_root = Path("/Users/test/workspace_123")

        container_path = WorkspacePathResolver.to_container_path(local_path, workspace_root)

        assert container_path == "/workspace/.claude/skills/my_skill"
        print(f" 路径转换: {local_path} -> {container_path}")

    def test_to_local_path(self):
        """测试容器路径 -> 本地路径"""
        container_path = "/workspace/.claude/skills/my_skill"
        workspace_root = Path("/Users/test/workspace_123")

        local_path = WorkspacePathResolver.to_local_path(container_path, workspace_root)

        expected = workspace_root / ".claude/skills/my_skill"
        assert local_path == expected
        print(f" 路径转换: {container_path} -> {local_path}")

    def test_batch_conversion(self):
        """测试批量转换"""
        workspace_root = Path("/Users/test/workspace_123")
        local_paths = [
            str(workspace_root / ".claude/skills/skill1"),
            str(workspace_root / ".claude/skills/skill2"),
            str(workspace_root / "data"),
        ]

        container_paths = WorkspacePathResolver.to_container_paths(local_paths, workspace_root)

        assert len(container_paths) == 3
        assert container_paths[0] == "/workspace/.claude/skills/skill1"
        assert container_paths[1] == "/workspace/.claude/skills/skill2"
        assert container_paths[2] == "/workspace/data"
        print(f" 批量转换成功: {len(container_paths)} 个路径")

    def test_absolute_path_handling(self):
        """测试绝对路径处理"""
        workspace_root = Path("/Users/test/workspace")

        # 测试绝对路径
        abs_path = Path("/Users/test/workspace/subdir/file.txt")
        container_path = WorkspacePathResolver.to_container_path(abs_path, workspace_root)
        assert container_path == "/workspace/subdir/file.txt"

    def test_relative_path_handling(self):
        """测试相对路径处理（需先构造为绝对路径）"""
        workspace_root = Path("/Users/test/workspace")

        # 相对路径需先组合为绝对路径
        abs_path = workspace_root / "subdir/file.txt"
        container_path = WorkspacePathResolver.to_container_path(abs_path, workspace_root)
        assert container_path == "/workspace/subdir/file.txt"

    def test_root_workspace_path(self):
        """测试工作空间根路径"""
        workspace_root = Path("/Users/test/workspace")

        container_path = WorkspacePathResolver.to_container_path(workspace_root, workspace_root)
        assert container_path == "/workspace"

    def test_round_trip_conversion(self):
        """测试往返转换"""
        workspace_root = Path("/Users/test/workspace")
        original_path = workspace_root / ".claude/skills/test_skill"

        # 本地 -> 容器 -> 本地
        container_path = WorkspacePathResolver.to_container_path(original_path, workspace_root)
        restored_path = WorkspacePathResolver.to_local_path(container_path, workspace_root)

        assert restored_path == original_path
