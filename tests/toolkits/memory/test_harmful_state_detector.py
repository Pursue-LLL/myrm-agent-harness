from myrm_agent_harness.core.security.detection.harmful_state_detector import scan_for_harmful_states


def test_scan_for_harmful_states():
    # Test safe text
    assert scan_for_harmful_states("I am feeling a bit sad today.") == []
    assert scan_for_harmful_states("My son has ADHD.") == []

    # Test self-harm
    assert len(scan_for_harmful_states("I want to kill myself")) > 0
    assert len(scan_for_harmful_states("不想活了")) > 0

    # Test severe depression
    assert len(scan_for_harmful_states("I am completely hopeless")) > 0
    assert len(scan_for_harmful_states("自己是个废物")) > 0

    # Test paranoia
    assert len(scan_for_harmful_states("someone is following me")) > 0
    assert len(scan_for_harmful_states("脑子里有芯片")) > 0

    # Test anxiety
    assert len(scan_for_harmful_states("I am having a panic attack")) > 0
    assert len(scan_for_harmful_states("喘不过气")) > 0
