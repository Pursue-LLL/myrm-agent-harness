from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_search.ast_parser import ASTParser


def test_ast_parser_python(tmp_path: Path):
    """Test AST parsing for Python files."""
    py_file = tmp_path / "test.py"
    py_file.write_text('''
class Database:
    def __init__(self):
        self.timeout = 30

    def connect(self):
        print("connecting")

def helper_func():
    pass
''')

    parser = ASTParser()

    # Test class method context
    ctx1 = parser.get_context_for_line(py_file, 4)
    assert ctx1 == "class Database -> def __init__"

    ctx2 = parser.get_context_for_line(py_file, 7)
    assert ctx2 == "class Database -> def connect"

    # Test top-level function context
    ctx3 = parser.get_context_for_line(py_file, 10)
    assert ctx3 == "def helper_func"

    # Test outside any function/class
    ctx4 = parser.get_context_for_line(py_file, 1)
    assert ctx4 is None

def test_ast_parser_typescript(tmp_path: Path):
    """Test AST parsing for TypeScript files."""
    ts_file = tmp_path / "test.ts"
    ts_file.write_text('''
interface User {
    id: number;
}

class UserService {
    private db: any;

    async getUser(id: number) {
        return await this.db.query(id);
    }
}

const helper = () => {
    console.log("help");
}
''')

    parser = ASTParser()

    ctx1 = parser.get_context_for_line(ts_file, 2)
    assert ctx1 == "interface User"

    ctx2 = parser.get_context_for_line(ts_file, 9)
    assert ctx2 == "class UserService -> def getUser"

    ctx3 = parser.get_context_for_line(ts_file, 14)
    assert ctx3 == "def helper"
