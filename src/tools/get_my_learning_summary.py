"""
Tool: get_my_learning_summary
Returns an aggregated learning snapshot: totals, completion stats, certificates,
and the 5 most recently enrolled courses.
Uses GET /course/v1/user/enrollment/list/{userId} — same as the portal's My Learning page.
"""
from __future__ import annotations

from client.sunbird_client import SunbirdApiError, authenticated_get, extract_sunbird_user_id
from schemas.tool_schemas import EnrolledCourse, GetMyLearningSummaryInput, GetMyLearningSummaryOutput

_STATUS_MAP = {0: "not_started", 1: "in_progress", 2: "completed"}

_FIELDS = "contentType,topic,name,channel,mimeType,appIcon,identifier,pkgVersion,trackable,primaryCategory"
_BATCH_DETAILS = "name,endDate,startDate,status,enrollmentType,createdBy,certificates"


def _parse_course(item: dict) -> EnrolledCourse:
    raw_status = item.get("status", 0)
    status_str = _STATUS_MAP.get(raw_status, "not_started")

    pct_raw = item.get("completionPercentage")
    completion_pct = float(pct_raw) if pct_raw is not None else 0.0

    content = item.get("contentDetails") or {}
    name = content.get("name") or item.get("courseId", "")

    certs = item.get("issuedCertificates") or []

    return EnrolledCourse(
        course_id=item.get("courseId", ""),
        course_name=name,
        completion_percentage=completion_pct,
        status=status_str,
        enrolled_date=item.get("enrolledDate", ""),
        has_certificate=len(certs) > 0,
    )


async def get_my_learning_summary(params: GetMyLearningSummaryInput) -> GetMyLearningSummaryOutput:
    user_id = extract_sunbird_user_id(params.user_token)
    if not user_id:
        return GetMyLearningSummaryOutput(
            user_id="",
            total_enrolled=0,
            completed=0,
            in_progress=0,
            not_started=0,
            certificates_earned=0,
            recent_courses=[],
            message="Could not extract user ID from token. Please call tool_login again.",
        )

    path = (
        f"/course/v1/user/enrollment/list/{user_id}"
        f"?fields={_FIELDS}&batchDetails={_BATCH_DETAILS}"
    )

    try:
        data = await authenticated_get(path, user_token=params.user_token)
    except SunbirdApiError as e:
        return GetMyLearningSummaryOutput(
            user_id=user_id,
            total_enrolled=0,
            completed=0,
            in_progress=0,
            not_started=0,
            certificates_earned=0,
            recent_courses=[],
            message=f"API error ({e.response_code}): {e}",
        )

    raw_list: list[dict] = data.get("result", {}).get("courses", [])
    courses = [_parse_course(item) for item in raw_list]

    completed = sum(1 for c in courses if c.status == "completed")
    in_progress = sum(1 for c in courses if c.status == "in_progress")
    not_started = sum(1 for c in courses if c.status == "not_started")
    certs = sum(1 for c in courses if c.has_certificate)

    try:
        sorted_courses = sorted(courses, key=lambda c: c.enrolled_date, reverse=True)
    except Exception:
        sorted_courses = courses

    return GetMyLearningSummaryOutput(
        user_id=user_id,
        total_enrolled=len(courses),
        completed=completed,
        in_progress=in_progress,
        not_started=not_started,
        certificates_earned=certs,
        recent_courses=sorted_courses[:5],
    )
