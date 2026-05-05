"""
Tool: track_content_progress
Marks a lesson or resource as consumed and updates the user's course progress.
Uses PATCH /course/v1/content/state/update (matching the portal player).
Also fires START + END telemetry events so the session is recorded in analytics.
"""
from __future__ import annotations

from datetime import datetime, timezone

from client.sunbird_client import SunbirdApiError, authenticated_patch, extract_sunbird_user_id
from client.telemetry_client import fire_content_telemetry
from schemas.tool_schemas import TrackContentProgressInput, TrackContentProgressOutput

_STATUS_INT = {"in_progress": 1, "completed": 2}


async def track_content_progress(params: TrackContentProgressInput) -> TrackContentProgressOutput:
    user_id = extract_sunbird_user_id(params.user_token)
    if not user_id:
        return TrackContentProgressOutput(
            success=False,
            content_id=params.content_id,
            course_id=params.course_id,
            new_status="",
            message="Could not extract user ID from token. Please call tool_login again.",
        )

    now = datetime.now(timezone.utc)
    last_access = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    status_int = _STATUS_INT[params.status]
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
                            "status": status_int,
                            "completionPercentage": params.completion_percentage,
                            "lastAccessTime": last_access,
                            "lastReadContentId": params.content_id,
                            "lastReadContentStatus": status_int,
                        }
                    ],
                }
            },
            user_token=params.user_token,
        )
    except SunbirdApiError as e:
        return TrackContentProgressOutput(
            success=False,
            content_id=params.content_id,
            course_id=params.course_id,
            new_status="",
            message=f"Progress update failed ({e.response_code}): {e}",
        )

    # Fire START + END telemetry so session is recorded in analytics
    await fire_content_telemetry(
        user_id=user_id,
        content_id=params.content_id,
        course_id=params.course_id,
        batch_id=params.batch_id,
        status=params.status,
        user_token=params.user_token,
    )

    return TrackContentProgressOutput(
        success=True,
        content_id=params.content_id,
        course_id=params.course_id,
        new_status=params.status,
        message=(
            f"Content {params.content_id} marked as '{params.status}' "
            f"({params.completion_percentage}% complete). Telemetry fired."
        ),
    )
