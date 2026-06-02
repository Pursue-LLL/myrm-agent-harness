import pytest
import zipfile
import io
from myrm_agent_harness.agent.skills.discovery.installers.batch_installer import HermesBatchParser

def create_mock_zip(files: dict) -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path, content in files.items():
            zip_file.writestr(file_path, content)
    return zip_buffer.getvalue()

@pytest.mark.asyncio
async def test_hermes_batch_parser_valid_zip():
    skill1_md = """---
name: translate_skill
description: Translate text
trigger_keywords: ["translate", "翻译"]
---
def translate():
    pass
"""
    skill2_md = """---
name: summarize_skill
description: Summarize text
---
def summarize():
    pass
"""
    files = {
        "translate_skill/SKILL.md": skill1_md,
        "translate_skill/utils.py": "def util(): pass",
        "summarize_skill/README.md": skill2_md,
        "ignored_root_file.txt": "ignore me"
    }
    zip_bytes = create_mock_zip(files)
    
    parser = HermesBatchParser()
    skills = parser.parse_zip(zip_bytes)
    
    assert len(skills) == 2
    
    # Verify translate_skill
    translate = next((s for s in skills if s.name == "translate_skill"), None)
    assert translate is not None
    assert translate.description == "Translate text [Keywords: translate, 翻译]"
    assert "def translate():" in translate.content
    assert "def util(): pass" in translate.content
    
    # Verify summarize_skill
    summarize = next((s for s in skills if s.name == "summarize_skill"), None)
    assert summarize is not None
    assert summarize.description == "Summarize text"

@pytest.mark.asyncio
async def test_hermes_batch_parser_empty_zip():
    zip_bytes = create_mock_zip({})
    parser = HermesBatchParser()
    skills = parser.parse_zip(zip_bytes)
    assert len(skills) == 0

@pytest.mark.asyncio
async def test_hermes_batch_parser_no_md():
    files = {
        "bad_skill/main.py": "def main(): pass",
    }
    zip_bytes = create_mock_zip(files)
    parser = HermesBatchParser()
    skills = parser.parse_zip(zip_bytes)
    # Still extracts it but uses fallback name
    assert len(skills) == 1
    assert skills[0].name == "bad_skill"
    assert skills[0].description == "Imported from batch zip"
    assert "def main(): pass" in skills[0].content
