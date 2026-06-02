from myrm_agent_harness.utils.db.fts5 import sanitize_fts5_query


def test_sanitize_fts5_query_strips_dangerous_chars():
    assert sanitize_fts5_query("hello +world") == "hello  world"
    assert sanitize_fts5_query("error {code}") == "error  code"
    assert sanitize_fts5_query("function(arg)") == "function arg"
    assert sanitize_fts5_query('unmatched"quote') == "unmatched quote"
    assert sanitize_fts5_query("start ^end") == "start  end"


def test_sanitize_fts5_preserves_quoted_phrases():
    assert sanitize_fts5_query('find "exact phrase here"') == 'find "exact phrase here"'
    assert sanitize_fts5_query('"phrase 1" AND "phrase 2"') == '"phrase 1" AND "phrase 2"'


def test_sanitize_fts5_quotes_hyphenated_terms():
    assert sanitize_fts5_query("npm-install") == '"npm-install"'
    assert sanitize_fts5_query("run my-script-name now") == 'run "my-script-name" now'
    assert sanitize_fts5_query('already "quoted-term"') == 'already "quoted-term"'


def test_sanitize_fts5_quotes_dotted_terms():
    assert sanitize_fts5_query("app.config.ts") == '"app.config.ts"'
    assert sanitize_fts5_query("version P2.2") == 'version "P2.2"'


def test_sanitize_fts5_handles_asterisks():
    assert sanitize_fts5_query("prefix*") == "prefix*"
    assert sanitize_fts5_query("prefix***") == "prefix*"
    assert sanitize_fts5_query("*suffix") == "suffix"
    assert sanitize_fts5_query(" * suffix") == "suffix"


def test_sanitize_fts5_removes_dangling_booleans():
    assert sanitize_fts5_query("AND hello") == "hello"
    assert sanitize_fts5_query("hello OR") == "hello"
    assert sanitize_fts5_query("NOT") == ""
    assert sanitize_fts5_query("valid AND query") == "valid AND query"


def test_sanitize_fts5_strips_angle_brackets_and_slashes():
    result = sanitize_fts5_query("<script>alert(1)</script>")
    assert "<" not in result
    assert ">" not in result
    assert "/" not in result

    result2 = sanitize_fts5_query("hello <b>world</b>")
    assert "<" not in result2
    assert ">" not in result2


def test_sanitize_fts5_strips_colons_and_special_punctuation():
    result = sanitize_fts5_query("column:value")
    assert ":" not in result

    result2 = sanitize_fts5_query("C:\\Users\\test")
    assert "\\" not in result2


def test_sanitize_fts5_handles_all_boolean_operators():
    assert sanitize_fts5_query("AND OR NOT") == ""
    assert sanitize_fts5_query("AND") == ""
    assert sanitize_fts5_query("OR") == ""


def test_sanitize_fts5_empty_and_whitespace():
    assert sanitize_fts5_query("") == ""
    assert sanitize_fts5_query("   ") == ""


def test_sanitize_fts5_strips_hyphens_preserves_compounds():
    assert sanitize_fts5_query("-negative") == "negative"
    assert sanitize_fts5_query("hello -world") == "hello  world"
    assert sanitize_fts5_query("---") == ""
    assert sanitize_fts5_query("-") == ""
    assert sanitize_fts5_query("hello---world") == "hello world"
    assert sanitize_fts5_query("chat-send") == '"chat-send"'
    assert sanitize_fts5_query("npm-install") == '"npm-install"'


def test_sanitize_fts5_strips_brackets_pipe_null():
    result = sanitize_fts5_query("[bracket]")
    assert "[" not in result
    assert "]" not in result
    result2 = sanitize_fts5_query("|pipe")
    assert "|" not in result2
    result3 = sanitize_fts5_query("\x00null")
    assert "\x00" not in result3


def test_sanitize_fts5_strips_near_operator():
    result = sanitize_fts5_query("NEAR")
    assert result == ""
    result2 = sanitize_fts5_query("hello NEAR world")
    assert "NEAR" not in result2
