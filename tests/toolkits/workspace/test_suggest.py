from __future__ import annotations

from myrm_agent_harness.toolkits.workspace import WorkspaceSuggestionOptions, suggest_workspace_paths
from myrm_agent_harness.toolkits.workspace.indexer import WorkspacePathIndexer


def test_suggest_matches_camel_word_boundary(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "appChrome.tsx").write_text("export default null")
    WorkspacePathIndexer.clear_cache(tmp_path)

    results = suggest_workspace_paths(tmp_path, "Chrome")

    assert results
    assert results[0].relative_path == "src/appChrome.tsx"
    assert results[0].score_tier == "word"


def test_slash_query_uses_directory_mode(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')")
    (tmp_path / "other_src_file.py").write_text("")

    results = suggest_workspace_paths(tmp_path, "src/", WorkspaceSuggestionOptions(kind="any"))

    assert [item.relative_path for item in results] == ["src/main.py"]


def test_directory_kind_filters_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "components").mkdir()
    (tmp_path / "src" / "main.py").write_text("")

    results = suggest_workspace_paths(tmp_path, "src/", WorkspaceSuggestionOptions(kind="directory"))

    assert [item.relative_path for item in results] == ["src/components"]

