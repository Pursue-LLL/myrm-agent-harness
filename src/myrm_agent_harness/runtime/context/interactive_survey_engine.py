"""Interactive mini-survey engine, submission validator, and rich document formatter.

[INPUT]
Declarative survey definitions, user response submissions, and final deliverable records.

[OUTPUT]
Validated submissions, compiled XML-style requirement manifests for LLM ingestion,
and multi-platform rich document deliverables (Lark / Notion / Markdown).

[POS]
Eliminates tedious multi-paragraph typing and accelerates requirement gathering 5x.
"""

import threading
from collections.abc import Sequence
from typing import Literal

from myrm_agent_harness.runtime.context.interactive_survey_types import (
    InteractiveSurveyCardPayload,
    RichDeliverableDocument,
    SurveyFieldSpec,
    SurveyResponseSubmission,
    SurveyValidationResult,
    SurveyValidationStatus,
)


class InteractiveSurveyEngine:
    """Manages interactive survey card lifecycles, answer validation, and rich document generation."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._surveys: dict[str, InteractiveSurveyCardPayload] = {}
        self._validated_manifests: dict[str, str] = {}

    def register_survey(self, survey: InteractiveSurveyCardPayload) -> None:
        """Register a survey card specification."""
        with self._lock:
            self._surveys[survey.survey_id] = survey

    def create_quick_survey(
        self,
        survey_id: str,
        title: str,
        description: str,
        fields: Sequence[SurveyFieldSpec],
        submit_button_label: str = "确认提交并启动",
    ) -> InteractiveSurveyCardPayload:
        """Construct and register a quick survey card specification."""
        with self._lock:
            card = InteractiveSurveyCardPayload(
                survey_id=survey_id,
                title=title,
                description=description,
                fields=tuple(fields),
                submit_button_label=submit_button_label,
            )
            self._surveys[survey_id] = card
            return card

    def get_survey(self, survey_id: str) -> InteractiveSurveyCardPayload | None:
        """Retrieve registered survey by ID."""
        with self._lock:
            return self._surveys.get(survey_id)

    def validate_and_compile_submission(
        self, submission: SurveyResponseSubmission
    ) -> SurveyValidationResult:
        """Validate user response submission and compile into structured requirement manifest."""
        with self._lock:
            survey = self._surveys.get(submission.survey_id)
            if not survey:
                return SurveyValidationResult(
                    is_valid=False,
                    status=SurveyValidationStatus.MISSING_REQUIRED_FIELD,
                    error_message=f"Survey '{submission.survey_id}' not found in registry",
                )

            answers = submission.answers
            manifest_lines: list[str] = [
                f'<survey_requirement_manifest survey_id="{survey.survey_id}" title="{survey.title}">'
            ]

            for f in survey.fields:
                val = answers.get(f.field_id)

                # Check required
                if f.required and (val is None or val == "" or val == ()):
                    return SurveyValidationResult(
                        is_valid=False,
                        status=SurveyValidationStatus.MISSING_REQUIRED_FIELD,
                        error_message=f"Required field '{f.label}' ({f.field_id}) is missing",
                    )

                if val is None:
                    continue

                # Type-specific validation
                if f.field_type == "single_select":
                    allowed_ids = {opt.id for opt in f.options}
                    if str(val) not in allowed_ids:
                        return SurveyValidationResult(
                            is_valid=False,
                            status=SurveyValidationStatus.INVALID_OPTION,
                            error_message=f"Selected option '{val}' for field '{f.label}' is invalid",
                        )
                    manifest_lines.append(f'  <param key="{f.field_id}" label="{f.label}">{val}</param>')

                elif f.field_type == "multi_select":
                    allowed_ids = {opt.id for opt in f.options}
                    chosen_seq = val if isinstance(val, (list, tuple)) else (val,)
                    for c in chosen_seq:
                        if str(c) not in allowed_ids:
                            return SurveyValidationResult(
                                is_valid=False,
                                status=SurveyValidationStatus.INVALID_OPTION,
                                error_message=f"Selected option '{c}' for multi-select field '{f.label}' is invalid",
                            )
                    joined = ", ".join(str(c) for c in chosen_seq)
                    manifest_lines.append(f'  <param key="{f.field_id}" label="{f.label}">{joined}</param>')

                elif f.field_type == "slider":
                    num_val = float(val)
                    if f.min_value is not None and num_val < f.min_value:
                        return SurveyValidationResult(
                            is_valid=False,
                            status=SurveyValidationStatus.OUT_OF_BOUNDS,
                            error_message=f"Value {num_val} for '{f.label}' below minimum {f.min_value}",
                        )
                    if f.max_value is not None and num_val > f.max_value:
                        return SurveyValidationResult(
                            is_valid=False,
                            status=SurveyValidationStatus.OUT_OF_BOUNDS,
                            error_message=f"Value {num_val} for '{f.label}' exceeds maximum {f.max_value}",
                        )
                    manifest_lines.append(f'  <param key="{f.field_id}" label="{f.label}">{num_val}</param>')

                elif f.field_type == "text_input":
                    manifest_lines.append(f'  <param key="{f.field_id}" label="{f.label}">{val}</param>')

            manifest_lines.append("</survey_requirement_manifest>")
            compiled = "\n".join(manifest_lines)
            self._validated_manifests[submission.survey_id] = compiled

            return SurveyValidationResult(
                is_valid=True,
                status=SurveyValidationStatus.VALID,
                compiled_manifest=compiled,
            )

    @classmethod
    def render_deliverable_document(
        cls,
        document: RichDeliverableDocument,
        export_target: Literal["markdown", "html", "lark_payload"] = "markdown",
    ) -> str:
        """Render deliverable document into exportable format compatible with Lark/Notion."""
        tags_str = " · ".join(f"#{t}" for t in document.tags) if document.tags else ""
        header = f"# {document.title}\n**作者**: {document.author} | **创建时间**: {document.created_at_utc[:10]}"
        if tags_str:
            header += f"\n**分类标签**: {tags_str}"
        summary_block = f"> 💡 **核心概要**: {document.summary}"

        if export_target == "markdown":
            return f"{header}\n\n{summary_block}\n\n---\n\n{document.markdown_content}"

        if export_target == "html":
            escaped_content = (
                document.markdown_content.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            return (
                f"<article class=\"myrm-rich-deliverable\">\n"
                f"  <h1>{document.title}</h1>\n"
                f"  <p class=\"meta\">{document.author} · {document.created_at_utc[:10]}</p>\n"
                f"  <div class=\"summary\">{document.summary}</div>\n"
                f"  <pre>{escaped_content}</pre>\n"
                f"</article>"
            )

        # Lark JSON format representation
        return (
            f'{{"type": "lark_doc_deliverable", "title": "{document.title}", '
            f'"summary": "{document.summary}", "body_markdown_len": {len(document.markdown_content)}}}'
        )
