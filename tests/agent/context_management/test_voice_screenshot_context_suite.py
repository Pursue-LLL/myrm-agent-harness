"""
Unit tests for VoiceScreenshotContextAwarenessSuite (Item 303).
Verifies heuristic intent detection, tile token budgeting, and multimodal context injection.
"""

from myrm_agent_harness.agent.context_management.voice_visual import (
    InjectedVoiceVisualTurn,
    VisualIntentCategory,
    VisualIntentDecision,
    VoiceScreenshotContext,
    VoiceScreenshotContextAwarenessSuite,
    VoiceVisualConfig,
    VoiceVisualContextInjector,
    VoiceVisualIntentDetector,
)


def test_visual_intent_error_diagnosis() -> None:
    detector = VoiceVisualIntentDetector()

    # Chinese error triggers
    res1 = detector.detect("请帮我看下这个报错怎么解决？")
    assert res1.has_visual_intent is True
    assert res1.category == VisualIntentCategory.ERROR_DIAGNOSIS
    assert res1.confidence >= 0.9

    # English error triggers
    res2 = detector.detect("Why does this error happen on my screen?")
    assert res2.has_visual_intent is True
    assert res2.category == VisualIntentCategory.ERROR_DIAGNOSIS


def test_visual_intent_ui_and_code() -> None:
    detector = VoiceVisualIntentDetector()

    # UI element trigger
    res_ui = detector.detect("这个按钮点了没反应，麻烦看一下")
    assert res_ui.has_visual_intent is True
    assert res_ui.category == VisualIntentCategory.UI_ELEMENT_QUERY

    # Code element trigger
    res_code = detector.detect("帮我检查下这段代码哪里写错了")
    assert res_code.has_visual_intent is True
    assert res_code.category == VisualIntentCategory.CODE_INSPECTION


def test_visual_intent_general_screen() -> None:
    detector = VoiceVisualIntentDetector()

    res_screen = detector.detect("屏幕上显示的是什么内容？")
    assert res_screen.has_visual_intent is True
    assert res_screen.category == VisualIntentCategory.GENERAL_SCREEN

    res_deictic = detector.detect("这里怎么填")
    assert res_deictic.has_visual_intent is True
    assert res_deictic.category == VisualIntentCategory.GENERAL_SCREEN


def test_non_visual_queries_bypass() -> None:
    detector = VoiceVisualIntentDetector()

    res1 = detector.detect("今天北京天气怎么样")
    assert res1.has_visual_intent is False
    assert res1.category == VisualIntentCategory.NO_VISUAL_INTENT
    assert len(res1.matched_triggers) == 0

    res2 = detector.detect("帮我写一个快速排序算法的 Python 实现")
    assert res2.has_visual_intent is False
    assert res2.category == VisualIntentCategory.NO_VISUAL_INTENT

    res3 = detector.detect("")
    assert res3.has_visual_intent is False


def test_token_cost_estimation_and_custom_triggers() -> None:
    config = VoiceVisualConfig(
        custom_triggers=["看这里特写"],
        default_tile_size=512,
        base_image_tokens=85,
        tokens_per_tile=170,
    )
    suite = VoiceScreenshotContextAwarenessSuite(config)

    # 1920x1080 -> 4x3 = 12 tiles -> 85 + 12 * 170 = 2125 tokens
    cost = suite.estimate_image_token_cost(1920, 1080)
    assert cost == 85 + (4 * 3 * 170)

    # Custom trigger test
    res = suite.detect_intent("请你看这里特写")
    assert res.has_visual_intent is True
    assert "看这里特写" in res.matched_triggers


def test_suite_end_to_end_multimodal_injection() -> None:
    suite = VoiceScreenshotContextAwarenessSuite()

    dummy_screenshot = VoiceScreenshotContext(
        image_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        mime_type="image/png",
        width=1920,
        height=1080,
        window_title="VSCode - main.py",
    )

    # 1. Turn with visual intent and screenshot attached
    turn_with_img = suite.process_voice_turn(
        transcript="这个报错怎么解决？",
        screenshot=dummy_screenshot,
    )
    assert turn_with_img.has_image is True
    assert turn_with_img.image_base64 == dummy_screenshot.image_base64
    assert turn_with_img.category == VisualIntentCategory.ERROR_DIAGNOSIS
    assert "VSCode - main.py" in turn_with_img.prompt_guidance
    assert "Visual Context" in turn_with_img.prompt_guidance
    assert turn_with_img.estimated_tokens > 1000

    # 2. Turn without visual intent even when screenshot passed
    turn_no_intent = suite.process_voice_turn(
        transcript="讲一个冷笑话",
        screenshot=dummy_screenshot,
    )
    assert turn_no_intent.has_image is False
    assert turn_no_intent.image_base64 is None
    assert turn_no_intent.estimated_tokens == 0

    # 3. Turn with visual intent but no screenshot provided
    turn_no_img = suite.process_voice_turn(
        transcript="看下这个报错",
        screenshot=None,
    )
    assert turn_no_img.has_image is False
    assert turn_no_img.image_base64 is None
    assert turn_no_img.category == VisualIntentCategory.ERROR_DIAGNOSIS
