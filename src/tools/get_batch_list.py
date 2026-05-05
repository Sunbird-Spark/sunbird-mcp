"""
Tool: get_batch_list
Lists all batches for a course with their status, enrollment type, and dates.
Works anonymously — no login required.
Useful before calling tool_enroll_in_course to pick the right batch_id.
"""
from __future__ import annotations

from datetime import datetime, timezone

from client.sunbird_client import SunbirdApiError, kong_post
from schemas.tool_schemas import BatchItem, GetBatchListInput, GetBatchListOutput

# Sunbird batch status integers
_STATUS_MAP = {0: "upcoming", 1: "active", 2: "expired"}
_STATUS_FILTER = {"upcoming": "0", "active": "1", "expired": "2"}


def _is_enrollable(batch: dict) -> bool:
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
    enroll_end: str = batch.get("enrollmentEndDate") or ""
    if enroll_end:
        try:
            enroll_dt = datetime.strptime(enroll_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if enroll_dt < datetime.now(timezone.utc):
                return False
        except ValueError:
            pass
    return True


def _parse_batch(b: dict) -> BatchItem:
    raw_status = int(b.get("status", 0))
    return BatchItem(
        batch_id=b.get("batchId", ""),
        name=b.get("name", ""),
        status=_STATUS_MAP.get(raw_status, "upcoming"),
        enrollment_type=b.get("enrollmentType", ""),
        start_date=b.get("startDate") or "",
        end_date=b.get("endDate") or "",
        enrollment_end_date=b.get("enrollmentEndDate") or "",
        created_by=b.get("createdBy") or "",
        is_enrollable=_is_enrollable(b),
    )


async def get_batch_list(params: GetBatchListInput) -> GetBatchListOutput:
    filters: dict = {"courseId": params.course_id}
    if params.status != "all":
        filters["status"] = _STATUS_FILTER[params.status]

    try:
        data = await kong_post(
            "/course/v1/batch/list",
            body={"request": {"filters": filters, "limit": 50}},
        )
    except SunbirdApiError as e:
        return GetBatchListOutput(
            course_id=params.course_id,
            total=0,
            batches=[],
        )

    raw: list[dict] = (
        data.get("result", {}).get("response", {}).get("content", [])
        or data.get("result", {}).get("content", [])
        or []
    )

    batches = [_parse_batch(b) for b in raw]

    return GetBatchListOutput(
        course_id=params.course_id,
        total=len(batches),
        batches=batches,
    )
