"""
Tool: submit_assessment
Submits a completed assessment with per-question scores and fires full telemetry.

This is the MCP equivalent of what the portal player does on assessment END:
  PATCH /course/v1/content/state/update  with:
    - contents[].status = 2 (completed)
    - assessments[] array carrying all ASSESS events + attempt metadata

Also fires START + ASSESS (per question) + END telemetry to analytics.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from client.sunbird_client import SunbirdApiError, authenticated_patch, extract_sunbird_user_id
from client.telemetry_client import fire_assessment_telemetry
from schemas.tool_schemas import SubmitAssessmentInput, SubmitAssessmentOutput


def _build_assess_event(q: "AssessmentQuestion", user_id: str, content_id: str, course_id: str, batch_id: str) -> dict:  # type: ignore[name-defined]
    """Build a single ASSESS telemetry event matching the portal's format."""
    import time, uuid
    return {
        "eid": "ASSESS",
        "ets": int(time.time() * 1000),
        "ver": "3.0",
        "mid": f"MCP:{uuid.uuid4()}",
        "actor": {"id": user_id, "type": "User"},
        "context": {
            "channel": "mcp",
            "pdata": {"id": "local.sunbird.mcp", "ver": "1.0", "pid": "sunbird-mcp"},
            "env": "content",
            "cdata": [
                {"id": course_id, "type": "Course"},
                {"id": batch_id, "type": "CourseBatch"},
            ],
            "rollup": {"l1": course_id},
        },
        "object": {
            "id": content_id,
            "type": "Content",
            "ver": "1.0",
            "rollup": {"l1": course_id, "l2": content_id},
        },
        "tags": [],
        "edata": {
            "item": {
                "id": q.id,
                "title": q.text,
                "maxscore": q.max_score,
                "type": "mcq",
                "exlength": 0,
                "params": [],
            },
            "index": q.index,
            "pass": "Yes" if q.score >= q.max_score else "No",
            "score": q.score,
            "resvalues": q.resvalues,
            "duration": q.duration,
        },
    }


async def submit_assessment(params: SubmitAssessmentInput) -> SubmitAssessmentOutput:
    user_id = extract_sunbird_user_id(params.user_token)
    if not user_id:
        return SubmitAssessmentOutput(
            success=False,
            content_id=params.content_id,
            course_id=params.course_id,
            total_score=0,
            max_score=params.max_score,
            percentage=0.0,
            pass_status=False,
            telemetry_fired=False,
            message="Could not extract user ID from token. Please call tool_login again.",
        )

    assessment_ts = int(time.time() * 1000)
    attempt_id = str(uuid.uuid4())
    last_access = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Build ASSESS events array — one per question answered
    assess_events = [
        _build_assess_event(q, user_id, params.content_id, params.course_id, params.batch_id)
        for q in params.questions
    ]

    # PATCH /course/v1/content/state/update with assessments[] array
    try:
        await authenticated_patch(
            "/course/v1/content/state/update",
            body={
                "request": {
                    "userId": user_id,
                    "contents": [
                        {
                            "contentId": params.content_id,
                            "batchId": params.batch_id,
                            "courseId": params.course_id,
                            "status": 2,  # completed
                            "completionPercentage": 100,
                            "lastAccessTime": last_access,
                            "lastReadContentId": params.content_id,
                            "lastReadContentStatus": 2,
                        }
                    ],
                    "assessments": [
                        {
                            "assessmentTs": assessment_ts,
                            "batchId": params.batch_id,
                            "courseId": params.course_id,
                            "userId": user_id,
                            "attemptId": attempt_id,
                            "contentId": params.content_id,
                            "events": assess_events,
                        }
                    ],
                }
            },
            user_token=params.user_token,
        )
    except SunbirdApiError as e:
        return SubmitAssessmentOutput(
            success=False,
            content_id=params.content_id,
            course_id=params.course_id,
            total_score=params.total_score,
            max_score=params.max_score,
            percentage=0.0,
            pass_status=False,
            telemetry_fired=False,
            message=f"Assessment submission failed ({e.response_code}): {e}",
        )

    percentage = round((params.total_score / params.max_score) * 100, 1) if params.max_score > 0 else 0.0
    pass_status = params.total_score >= (params.max_score * 0.5)  # 50% pass threshold

    # Fire full assessment telemetry (START + ASSESS per question + END)
    questions_for_telemetry = [
        {
            "id": q.id,
            "text": q.text,
            "index": q.index,
            "score": q.score,
            "max_score": q.max_score,
            "resvalues": q.resvalues,
            "duration": q.duration,
        }
        for q in params.questions
    ]
    await fire_assessment_telemetry(
        user_id=user_id,
        content_id=params.content_id,
        course_id=params.course_id,
        batch_id=params.batch_id,
        user_token=params.user_token,
        questions_attempted=questions_for_telemetry,
        total_score=params.total_score,
        max_score=params.max_score,
        duration_sec=params.duration_sec,
    )

    return SubmitAssessmentOutput(
        success=True,
        content_id=params.content_id,
        course_id=params.course_id,
        total_score=params.total_score,
        max_score=params.max_score,
        percentage=percentage,
        pass_status=pass_status,
        telemetry_fired=True,
        message=(
            f"Assessment submitted. Score: {params.total_score}/{params.max_score} "
            f"({percentage}%) — {'Pass' if pass_status else 'Fail'}. "
            f"Telemetry fired with {len(params.questions)} ASSESS events."
        ),
    )
