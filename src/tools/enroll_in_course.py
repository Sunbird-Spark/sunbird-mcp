"""
Tool: enroll_in_course
Enrolls the logged-in user in a course batch.
Auto-selects the first active open batch if batch_id is not provided.
Batch criteria: status=1 (ongoing), enrollmentType=open, endDate in future.
"""
from __future__ import annotations

from datetime import datetime, timezone

from client.sunbird_client import SunbirdApiError, authenticated_post, extract_sunbird_user_id, kong_post
from schemas.tool_schemas import EnrollInCourseInput, EnrollInCourseOutput


def _is_batch_enrollable(batch: dict) -> bool:
    """Return True only if the batch is ongoing, open-enrollment, and not yet expired."""
    if batch.get("enrollmentType") != "open":
        return False
    if str(batch.get("status", "0")) != "1":
        return False
    end_date: str = batch.get("endDate") or ""
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if end_dt < datetime.now(timezone.utc):
                return False
        except ValueError:
            pass
    return True


async def _find_enrollable_batch(course_id: str) -> tuple[str, str] | tuple[None, None]:
    """
    Return (batchId, batchName) for the first enrollable batch, or (None, None).
    Fetches all active batches for the course and applies _is_batch_enrollable filter.
    """
    try:
        data = await kong_post(
            "/course/v1/batch/list",
            body={
                "request": {
                    "filters": {
                        "courseId": course_id,
                        "status": "1",
                        "enrollmentType": "open",
                    },
                    "limit": 20,
                }
            },
        )
        batches: list[dict] = (
            data.get("result", {}).get("response", {}).get("content", [])
            or data.get("result", {}).get("content", [])
            or []
        )
        for batch in batches:
            if _is_batch_enrollable(batch):
                return batch.get("batchId", ""), batch.get("name", "")
        return None, None
    except SunbirdApiError:
        return None, None


async def enroll_in_course(params: EnrollInCourseInput) -> EnrollInCourseOutput:
    user_id = extract_sunbird_user_id(params.user_token)
    if not user_id:
        return EnrollInCourseOutput(
            success=False,
            course_id=params.course_id,
            batch_id="",
            message="Could not extract user ID from token. Please call tool_login again.",
        )

    batch_id = params.batch_id
    batch_name = ""

    if not batch_id:
        batch_id, batch_name = await _find_enrollable_batch(params.course_id)
        if not batch_id:
            return EnrollInCourseOutput(
                success=False,
                course_id=params.course_id,
                batch_id="",
                message=(
                    "No active open batch found for this course. "
                    "The course may not have an ongoing batch or enrollment may be closed."
                ),
            )

    try:
        await authenticated_post(
            "/course/v1/enrol",
            body={
                "request": {
                    "courseId": params.course_id,
                    "batchId": batch_id,
                    "userId": user_id,
                }
            },
            user_token=params.user_token,
        )
    except SunbirdApiError as e:
        raw = str(e)
        # Already enrolled — treat as success
        if "USER_ALREADY_ENROLLED_COURSE" in raw or "already Enrolled" in raw:
            return EnrollInCourseOutput(
                success=True,
                course_id=params.course_id,
                batch_id=batch_id,
                message="Already enrolled in this course.",
            )
        return EnrollInCourseOutput(
            success=False,
            course_id=params.course_id,
            batch_id=batch_id,
            message=f"Enrollment failed ({e.response_code}): {raw}",
        )

    label = f" ({batch_name})" if batch_name else ""
    return EnrollInCourseOutput(
        success=True,
        course_id=params.course_id,
        batch_id=batch_id,
        message=f"Successfully enrolled in course {params.course_id}, batch{label} {batch_id}.",
    )
