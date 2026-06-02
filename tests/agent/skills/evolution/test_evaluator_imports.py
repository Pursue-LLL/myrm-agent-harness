import pytest

from myrm_agent_harness.agent.skills.evolution.execution.evaluator import BatchEvaluator


@pytest.mark.asyncio
async def test_evaluator_detects_bad_imports():
    evaluator = BatchEvaluator()

    # Valid code
    good_code = "```python\nimport os\nimport sys\nfrom datetime import datetime\n```"
    is_valid, msg = evaluator._dry_run_validation(good_code)
    assert is_valid

    # Bad import (standard)
    bad_import = "```python\nimport definitely_not_a_real_module_12345\n```"
    is_valid, msg = evaluator._dry_run_validation(bad_import)
    assert not is_valid
    assert "ModuleNotFoundError" in msg
    assert "definitely_not_a_real_module_12345" in msg

    # Bad import (from)
    bad_from = "```python\nfrom hallucinated_package.module import function\n```"
    is_valid, msg = evaluator._dry_run_validation(bad_from)
    assert not is_valid
    assert "ModuleNotFoundError" in msg
    assert "hallucinated_package" in msg
