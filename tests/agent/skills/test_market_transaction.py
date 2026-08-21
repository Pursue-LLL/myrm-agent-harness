"""Tests for SkillInstallTransaction and SkillInstallReceipt."""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.market.transaction import (
    SkillInstallTransaction,
    build_skill_receipt,
    compute_files_digest,
    read_receipt_file,
    write_receipt_file,
)


def test_compute_files_digest():
    files = {
        "SKILL.md": b"# Test Skill",
        "index.js": b"console.log('hello');",
    }
    digests, manifest_hash = compute_files_digest(files)
    assert len(digests) == 2
    assert digests[0].relative_path == "SKILL.md"
    assert digests[1].relative_path == "index.js"
    assert manifest_hash != ""


def test_build_and_write_read_receipt(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    files = {
        "SKILL.md": b"# Test Skill",
    }
    receipt = build_skill_receipt(
        skill_id="test_skill_1",
        skill_name="my-skill",
        source="clawhub",
        installed_path=str(skill_dir),
        files=files,
        version="1.2.0",
        installed_skills=["test_skill_1"],
        declared_mcp_servers=["mcp_server_a"],
        scan_score=95,
        security_verified=True,
    )
    assert receipt.skill_id == "test_skill_1"
    assert receipt.version == "1.2.0"
    assert receipt.receipt_id.startswith("rcpt_")

    write_receipt_file(skill_dir, receipt)
    loaded = read_receipt_file(skill_dir)
    assert loaded is not None
    assert loaded.receipt_id == receipt.receipt_id
    assert loaded.skill_id == "test_skill_1"
    assert loaded.version == "1.2.0"
    assert len(loaded.files) == 1
    assert loaded.files[0].relative_path == "SKILL.md"


def test_transaction_commit(tmp_path: Path):
    target_dir = tmp_path / "installed_skill"
    source_dir = tmp_path / "source_temp"
    source_dir.mkdir()
    (source_dir / "SKILL.md").write_text("# Source", encoding="utf-8")

    with SkillInstallTransaction() as tx:
        tx.stage_replace(source_dir, target_dir)

    assert target_dir.exists()
    assert (target_dir / "SKILL.md").read_text(encoding="utf-8") == "# Source"


def test_transaction_rollback_on_exception(tmp_path: Path):
    target_dir = tmp_path / "installed_skill"
    target_dir.mkdir()
    (target_dir / "old.txt").write_text("old content", encoding="utf-8")

    source_dir = tmp_path / "source_temp"
    source_dir.mkdir()
    (source_dir / "new.txt").write_text("new content", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with SkillInstallTransaction() as tx:
            tx.stage_replace(source_dir, target_dir)
            assert (target_dir / "new.txt").exists()
            raise RuntimeError("Simulation error during install")

    # Target should be rolled back to original content
    assert target_dir.exists()
    assert (target_dir / "old.txt").read_text(encoding="utf-8") == "old content"
    assert not (target_dir / "new.txt").exists()
