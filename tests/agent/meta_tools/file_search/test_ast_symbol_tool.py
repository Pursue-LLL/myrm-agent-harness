import pytest
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_search.ast_symbol_tool import (
    extract_symbols_from_code,
    create_ast_symbol_search_tool,
)


def test_extract_python_symbols():
    code = '''
"""Module docstring."""

class UserService:
    """User service for authentication."""

    def __init__(self, db_conn):
        self.db = db_conn

    async def get_user_by_id(self, user_id: int) -> dict:
        """Fetch user by id."""
        return {"id": user_id}

def standalone_helper(x: int) -> int:
    return x * 2
'''
    symbols = extract_symbols_from_code(code, "test_service.py")
    assert len(symbols) == 4

    names = [s.name for s in symbols]
    assert "UserService" in names
    assert "__init__" in names
    assert "get_user_by_id" in names
    assert "standalone_helper" in names

    cls_symbol = next(s for s in symbols if s.name == "UserService")
    assert cls_symbol.kind == "class"
    assert cls_symbol.docstring_summary == "User service for authentication."

    method_symbol = next(s for s in symbols if s.name == "get_user_by_id")
    assert method_symbol.kind == "method"
    assert method_symbol.container == "UserService"
    assert "async def get_user_by_id" in method_symbol.signature


def test_extract_typescript_symbols():
    code = '''
export interface UserProfile {
    id: string;
    email: string;
}

export type AuthState = 'authenticated' | 'unauthenticated';

export class SessionManager {
    private token: string;

    constructor() {}
}

export async function loginWithOidc(provider: string): Promise<boolean> {
    return true;
}

export const renderBadge = (count: number) => {
    return null;
};
'''
    symbols = extract_symbols_from_code(code, "auth.ts")
    names = [s.name for s in symbols]
    assert "UserProfile" in names
    assert "AuthState" in names
    assert "SessionManager" in names
    assert "loginWithOidc" in names
    assert "renderBadge" in names

    iface = next(s for s in symbols if s.name == "UserProfile")
    assert iface.kind == "interface"


def test_extract_go_rust_symbols():
    go_code = '''
package main

type Config struct {
    Port int
}

func (c *Config) Validate() bool {
    return true
}

func main() {}
'''
    go_symbols = extract_symbols_from_code(go_code, "main.go")
    go_names = [s.name for s in go_symbols]
    assert "Config" in go_names
    assert "Validate" in go_names
    assert "main" in go_names

    rust_code = '''
pub struct TokenStore {
    secret: String,
}

pub enum Role {
    Admin,
    User,
}

pub fn verify_signature(data: &[u8]) -> bool {
    true
}
'''
    rust_symbols = extract_symbols_from_code(rust_code, "lib.rs")
    rust_names = [s.name for s in rust_symbols]
    assert "TokenStore" in rust_names
    assert "Role" in rust_names
    assert "verify_signature" in rust_names
