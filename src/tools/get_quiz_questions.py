"""
Tool 3 — get_quiz_questions

Fetch all questions from a question set for a conversational quiz.
Handles two Sunbird question formats:

  A) QuestionSet v2 (objectType=QuestionSet):
       GET /questionset/v2/hierarchy/{id}  → walk tree for Question IDs
       POST /question/v2/list              → fetch question bodies in chunks of 20

  B) SelfAssess / Course Assessment (contentType=SelfAssess):
       GET /content/v1/read/{id}           → get AssessmentItem IDs from content.questions[]
       GET /assessment/v1/items/read/{id}  → fetch each item (parallel, groups of 5)
       Parse ECML body JSON                → extract text, MCQ options, correct answer
"""
from __future__ import annotations

import asyncio
import json
import logging

from client.sunbird_client import SunbirdApiError, kong_get, kong_post
from schemas.tool_schemas import (
    GetQuizQuestionsInput,
    GetQuizQuestionsOutput,
    QuizOption,
    QuizQuestion,
)

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 20
_BATCH_SIZE = 5


# ── QuestionSet v2 helpers ────────────────────────────────────────────────────

def _collect_question_ids(node: dict) -> list[str]:
    """Recursively collect all Question identifiers from a v2 questionSet hierarchy."""
    ids: list[str] = []
    if node.get("objectType") == "Question":
        if node.get("identifier"):
            ids.append(node["identifier"])
        return ids
    for child in node.get("children") or []:
        ids.extend(_collect_question_ids(child))
    return ids


def _parse_v2_options(interaction: dict) -> tuple[list[QuizOption], str]:
    """Extract MCQ options and correct answer label from a v2 question interaction block."""
    options: list[QuizOption] = []
    correct_answer = ""

    response_declaration = interaction.get("response1") or {}
    correct_value = str(response_declaration.get("correctResponse", {}).get("value", ""))

    for opt in interaction.get("options") or []:
        label = opt.get("label", "")
        value = str(opt.get("value", ""))
        options.append(QuizOption(label=label, value=value))
        if value == correct_value:
            correct_answer = label

    return options, correct_answer


def _parse_v2_question(q: dict) -> QuizQuestion:
    """Map a raw v2 question dict to QuizQuestion."""
    body = q.get("body") or q.get("editorState", {}).get("question") or ""
    interaction = q.get("interactions") or q.get("interaction") or {}
    options, correct_answer = _parse_v2_options(interaction)

    hints = q.get("hints") or {}
    hint_text: str | None = None
    if hints:
        hint_text = next(iter(hints.values()), None) if isinstance(hints, dict) else str(hints)

    return QuizQuestion(
        id=q.get("identifier", ""),
        text=body,
        options=options,
        correct_answer=correct_answer,
        max_score=float(q.get("maxScore") or 1),
        hint=hint_text,
    )


# ── SelfAssess / AssessmentItem helpers ───────────────────────────────────────

def _parse_ecml_body(raw_body: str | None) -> tuple[str, list[QuizOption], str, str | None]:
    """
    Parse an ECML body JSON string.
    Returns (question_text, options, correct_answer, hint).
    Supports MCQ, MTF (match the following), and word-arrangement types.
    """
    if not raw_body:
        return "", [], "", None

    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError):
        return raw_body or "", [], "", None

    data = body.get("data", {}).get("data", {})
    question_text: str = data.get("question", {}).get("text", "")
    hint: str | None = data.get("question", {}).get("hint") or None

    options: list[QuizOption] = []
    correct_answer = ""

    raw_options = data.get("options") or []

    if raw_options:
        # MCQ — options list with isCorrect flag
        for i, opt in enumerate(raw_options):
            label = opt.get("text", f"Option {i+1}")
            value = str(i)
            options.append(QuizOption(label=label, value=value))
            if opt.get("isCorrect"):
                correct_answer = label

    elif data.get("option", {}).get("optionsLHS"):
        # MTF (match the following) — present as flattened text
        lhs = data["option"]["optionsLHS"]
        rhs = data["option"].get("optionsRHS", [])
        for i, (l, r) in enumerate(zip(lhs, rhs)):
            label = f"{l.get('text','').strip()} → {r.get('text','').strip()}"
            options.append(QuizOption(label=label, value=str(i)))
        correct_answer = " | ".join(o.label for o in options)

    elif data.get("sentence"):
        # Word arrangement — present the target sentence as correct answer
        sentence = data["sentence"]
        tabs = sentence.get("tabs") or []
        for i, tab in enumerate(tabs):
            options.append(QuizOption(label=tab.get("text", ""), value=str(i)))
        correct_answer = sentence.get("text", "")

    return question_text, options, correct_answer, hint


async def _fetch_assessment_items(ids: list[str]) -> list[QuizQuestion]:
    """Fetch AssessmentItems in parallel batches of _BATCH_SIZE and parse each."""
    questions: list[QuizQuestion] = []
    for i in range(0, len(ids), _BATCH_SIZE):
        batch = ids[i : i + _BATCH_SIZE]
        results: list[dict | BaseException] = await asyncio.gather(
            *[kong_get(f"/assessment/v1/items/read/{cid}") for cid in batch],
            return_exceptions=True,
        )
        for item_id, res in zip(batch, results):
            if isinstance(res, BaseException):
                logger.warning("Failed to fetch assessment item %s: %s", item_id, res)
                continue
            item = res.get("result", {}).get("assessment_item", {})
            if not item:
                continue
            text, options, correct_answer, hint = _parse_ecml_body(item.get("body"))
            questions.append(
                QuizQuestion(
                    id=item.get("identifier", item_id),
                    text=text,
                    options=options,
                    correct_answer=correct_answer,
                    max_score=float(item.get("maxScore") or 1),
                    hint=hint,
                )
            )
    return questions


# ── main handler ──────────────────────────────────────────────────────────────

async def get_quiz_questions(params: GetQuizQuestionsInput) -> GetQuizQuestionsOutput:
    """
    Tool 3: Fetch all questions from a question set to run a conversational quiz.
    Auto-detects SelfAssess (ECML) vs QuestionSet v2 format.
    """
    try:
        # Probe: read the content to determine format
        probe = await kong_get(f"/content/v1/read/{params.question_set_id}")
        content = probe.get("result", {}).get("content", {})
        content_type = content.get("contentType", "")
        object_type = content.get("objectType", "")
        title: str = content.get("name", params.question_set_id)

        # ── Path B: SelfAssess (ECML-based Course Assessment) ──────────────────
        if content_type == "SelfAssess" or (
            object_type == "Content" and content.get("primaryCategory") == "Course Assessment"
        ):
            question_refs: list[dict] = content.get("questions") or []
            if not question_refs:
                return GetQuizQuestionsOutput(
                    question_set_id=params.question_set_id,
                    title=title,
                    total_questions=0,
                    questions=[],
                )
            ids = [q["identifier"] for q in question_refs if q.get("identifier")]
            questions = await _fetch_assessment_items(ids)
            return GetQuizQuestionsOutput(
                question_set_id=params.question_set_id,
                title=title,
                total_questions=len(questions),
                questions=questions,
            )

        # ── Path A: QuestionSet v2 ─────────────────────────────────────────────
        hierarchy_data = await kong_get(f"/questionset/v2/hierarchy/{params.question_set_id}")
        question_set = (
            hierarchy_data.get("result", {}).get("questionSet")
            or hierarchy_data.get("result", {}).get("questionset")
            or {}
        )
        title = question_set.get("name", title)
        question_ids = _collect_question_ids(question_set)

        if not question_ids:
            return GetQuizQuestionsOutput(
                question_set_id=params.question_set_id,
                title=title,
                total_questions=0,
                questions=[],
            )

        chunks = [
            question_ids[i : i + _CHUNK_SIZE]
            for i in range(0, len(question_ids), _CHUNK_SIZE)
        ]
        chunk_results: list[dict | BaseException] = await asyncio.gather(
            *[
                kong_post(
                    "/question/v2/list",
                    {"request": {"search": {"identifier": chunk}}},
                )
                for chunk in chunks
            ],
            return_exceptions=True,
        )

        raw_questions: list[dict] = []
        for res in chunk_results:
            if isinstance(res, BaseException):
                continue
            raw_questions.extend(
                res.get("result", {}).get("questions")
                or res.get("result", {}).get("question")
                or []
            )

        questions = [_parse_v2_question(q) for q in raw_questions]
        return GetQuizQuestionsOutput(
            question_set_id=params.question_set_id,
            title=title,
            total_questions=len(questions),
            questions=questions,
        )

    except SunbirdApiError:
        raise
    except Exception as exc:
        raise ValueError(f"get_quiz_questions failed unexpectedly: {exc}") from exc
