"""Unit tests for interactive survey engine, submission validation, and deliverable rendering.

[INPUT]
Declarative survey schemas, valid/invalid user submissions, and deliverable document objects.

[OUTPUT]
Verification of validation statuses, compiled manifests, export templates, and thread safety.

[POS]
Quality gate for Item 119: InteractiveMiniSurveyAndStructuredRequirementFormCard.
"""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.runtime.context.interactive_survey_engine import (
    InteractiveSurveyEngine,
)
from myrm_agent_harness.runtime.context.interactive_survey_types import (
    RichDeliverableDocument,
    SurveyFieldOption,
    SurveyFieldSpec,
    SurveyResponseSubmission,
    SurveyValidationStatus,
)


def test_survey_registration_and_retrieval() -> None:
    engine = InteractiveSurveyEngine()
    fields = (
        SurveyFieldSpec(
            field_id="style",
            label="视觉风格",
            field_type="single_select",
            required=True,
            options=(
                SurveyFieldOption(id="tech", label="未来科技感"),
                SurveyFieldOption(id="warm", label="极简暖色调"),
            ),
        ),
    )
    card = engine.create_quick_survey(
        survey_id="survey_101",
        title="产品落地页风格偏好",
        description="请选择您心仪的主色调与布局",
        fields=fields,
    )
    assert card.survey_id == "survey_101"
    retrieved = engine.get_survey("survey_101")
    assert retrieved is not None
    assert retrieved.title == "产品落地页风格偏好"
    assert len(retrieved.fields) == 1


def test_survey_validation_success_and_manifest() -> None:
    engine = InteractiveSurveyEngine()
    fields = (
        SurveyFieldSpec(
            field_id="target_audience",
            label="目标客群",
            field_type="single_select",
            required=True,
            options=(
                SurveyFieldOption(id="b2b", label="企业客户"),
                SurveyFieldOption(id="c_end", label="个人创作者"),
            ),
        ),
        SurveyFieldSpec(
            field_id="platforms",
            label="分发平台",
            field_type="multi_select",
            required=True,
            options=(
                SurveyFieldOption(id="web", label="Web端"),
                SurveyFieldOption(id="mobile", label="移动端APP"),
                SurveyFieldOption(id="desktop", label="桌面客户端"),
            ),
        ),
        SurveyFieldSpec(
            field_id="budget_ratio",
            label="预算偏好权重",
            field_type="slider",
            min_value=0.0,
            max_value=1.0,
            required=True,
        ),
        SurveyFieldSpec(
            field_id="notes",
            label="特殊补充",
            field_type="text_input",
            required=False,
        ),
    )
    engine.create_quick_survey(
        survey_id="survey_proj",
        title="项目立项问卷",
        description="收集前期核心诉求",
        fields=fields,
    )

    submission = SurveyResponseSubmission(
        survey_id="survey_proj",
        answers={
            "target_audience": "b2b",
            "platforms": ("web", "desktop"),
            "budget_ratio": 0.85,
            "notes": "优先支持暗黑模式",
        },
    )

    result = engine.validate_and_compile_submission(submission)
    assert result.is_valid is True
    assert result.status == SurveyValidationStatus.VALID
    assert result.compiled_manifest is not None
    assert '<survey_requirement_manifest survey_id="survey_proj"' in result.compiled_manifest
    assert '<param key="target_audience" label="目标客群">b2b</param>' in result.compiled_manifest
    assert '<param key="platforms" label="分发平台">web, desktop</param>' in result.compiled_manifest
    assert '<param key="budget_ratio" label="预算偏好权重">0.85</param>' in result.compiled_manifest
    assert '<param key="notes" label="特殊补充">优先支持暗黑模式</param>' in result.compiled_manifest


def test_survey_missing_required_field_rejection() -> None:
    engine = InteractiveSurveyEngine()
    fields = (
        SurveyFieldSpec(
            field_id="name",
            label="项目代号",
            field_type="text_input",
            required=True,
        ),
    )
    engine.create_quick_survey(
        survey_id="survey_req",
        title="必填检查",
        description="说明",
        fields=fields,
    )

    # Empty submission
    submission = SurveyResponseSubmission(
        survey_id="survey_req",
        answers={},
    )
    res = engine.validate_and_compile_submission(submission)
    assert res.is_valid is False
    assert res.status == SurveyValidationStatus.MISSING_REQUIRED_FIELD
    assert "Required field" in (res.error_message or "")

    # Non-existent survey ID
    ghost_submission = SurveyResponseSubmission(
        survey_id="ghost_survey",
        answers={"foo": "bar"},
    )
    ghost_res = engine.validate_and_compile_submission(ghost_submission)
    assert ghost_res.is_valid is False
    assert ghost_res.status == SurveyValidationStatus.MISSING_REQUIRED_FIELD


def test_survey_invalid_option_and_out_of_bounds() -> None:
    engine = InteractiveSurveyEngine()
    fields = (
        SurveyFieldSpec(
            field_id="tier",
            label="服务层级",
            field_type="single_select",
            required=True,
            options=(
                SurveyFieldOption(id="pro", label="专业版"),
            ),
        ),
        SurveyFieldSpec(
            field_id="tags",
            label="标贴",
            field_type="multi_select",
            required=True,
            options=(
                SurveyFieldOption(id="tag1", label="标贴一"),
            ),
        ),
        SurveyFieldSpec(
            field_id="scale",
            label="量级",
            field_type="slider",
            min_value=1.0,
            max_value=10.0,
            required=True,
        ),
    )
    engine.create_quick_survey(
        survey_id="survey_boundary",
        title="边界检查",
        description="说明",
        fields=fields,
    )

    # 1. Invalid single select
    sub_inv_single = SurveyResponseSubmission(
        survey_id="survey_boundary",
        answers={"tier": "vip_unknown", "tags": ("tag1",), "scale": 5.0},
    )
    res1 = engine.validate_and_compile_submission(sub_inv_single)
    assert res1.is_valid is False
    assert res1.status == SurveyValidationStatus.INVALID_OPTION

    # 2. Invalid multi select
    sub_inv_multi = SurveyResponseSubmission(
        survey_id="survey_boundary",
        answers={"tier": "pro", "tags": ("tag1", "invalid_tag"), "scale": 5.0},
    )
    res2 = engine.validate_and_compile_submission(sub_inv_multi)
    assert res2.is_valid is False
    assert res2.status == SurveyValidationStatus.INVALID_OPTION

    # 3. Slider underflow
    sub_under = SurveyResponseSubmission(
        survey_id="survey_boundary",
        answers={"tier": "pro", "tags": ("tag1",), "scale": 0.5},
    )
    res3 = engine.validate_and_compile_submission(sub_under)
    assert res3.is_valid is False
    assert res3.status == SurveyValidationStatus.OUT_OF_BOUNDS

    # 4. Slider overflow
    sub_over = SurveyResponseSubmission(
        survey_id="survey_boundary",
        answers={"tier": "pro", "tags": ("tag1",), "scale": 15.0},
    )
    res4 = engine.validate_and_compile_submission(sub_over)
    assert res4.is_valid is False
    assert res4.status == SurveyValidationStatus.OUT_OF_BOUNDS


def test_rich_deliverable_document_rendering() -> None:
    doc = RichDeliverableDocument(
        document_id="doc_2026",
        title="2026产品架构设计终稿",
        author="Myrm Architect",
        summary="完成混合沙箱与微内核全链路闭环，端到端性能提升3.8x",
        markdown_content="### 架构全景图\n- 第一层: 控制平面\n- 第二层: 沙箱执行\n- 第三层: 运行时引擎",
        tags=("架构", "里程碑", "发布"),
    )

    # Markdown
    md_output = InteractiveSurveyEngine.render_deliverable_document(doc, "markdown")
    assert "# 2026产品架构设计终稿" in md_output
    assert "Myrm Architect" in md_output
    assert "#架构 · #里程碑 · #发布" in md_output
    assert "完成混合沙箱与微内核全链路闭环" in md_output
    assert "### 架构全景图" in md_output

    # HTML
    html_output = InteractiveSurveyEngine.render_deliverable_document(doc, "html")
    assert "<article class=\"myrm-rich-deliverable\">" in html_output
    assert "<h1>2026产品架构设计终稿</h1>" in html_output
    assert "<pre>### 架构全景图" in html_output

    # Lark payload
    lark_output = InteractiveSurveyEngine.render_deliverable_document(doc, "lark_payload")
    assert "lark_doc_deliverable" in lark_output
    assert "2026产品架构设计终稿" in lark_output


def test_survey_engine_thread_safety() -> None:
    engine = InteractiveSurveyEngine()

    def worker(worker_id: int) -> bool:
        sid = f"survey_{worker_id}"
        engine.create_quick_survey(
            survey_id=sid,
            title=f"Survey {worker_id}",
            description="desc",
            fields=(
                SurveyFieldSpec(
                    field_id="choice",
                    label="Choice",
                    field_type="single_select",
                    options=(SurveyFieldOption(id="a", label="A"),),
                ),
            ),
        )
        res = engine.validate_and_compile_submission(
            SurveyResponseSubmission(
                survey_id=sid,
                answers={"choice": "a"},
            )
        )
        return res.is_valid

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(20)]
        results = [f.result() for f in futures]

    assert all(results)
    assert len(engine._surveys) == 20
