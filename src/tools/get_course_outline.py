"""
Tool 2 — get_course_outline

Fetch and flatten a course's full unit/lesson hierarchy.

Steps:
  1. GET /course/v1/hierarchy/{courseId}
  2. Walk tree: top-level children = units, their children = lessons
  3. For leaves missing mimeType, batch-fetch via /content/v1/read/{id}
     in groups of 5 using asyncio.gather
  4. Return structured unit/lesson outline
"""
from __future__ import annotations

import asyncio

from client.sunbird_client import SunbirdApiError, build_consume_url, kong_get
from schemas.tool_schemas import (
    GetCourseOutlineInput,
    GetCourseOutlineOutput,
    OutlineLesson,
    OutlineUnit,
)

_BATCH_SIZE = 5


def _duration_to_minutes(duration: int | str | None) -> float | None:
    if duration is None:
        return None
    try:
        secs = int(duration)
        return round(secs / 60, 1) if secs > 0 else None
    except (ValueError, TypeError):
        return None


async def _fetch_mime_types(ids: list[str]) -> dict[str, str]:
    """Batch-fetch mimeType for a list of content IDs, in groups of _BATCH_SIZE."""
    if not ids:
        return {}

    results: dict[str, str] = {}
    for i in range(0, len(ids), _BATCH_SIZE):
        batch = ids[i : i + _BATCH_SIZE]
        responses: list[dict | BaseException] = await asyncio.gather(
            *[kong_get(f"/content/v1/read/{cid}?fields=mimeType,duration") for cid in batch],
            return_exceptions=True,
        )
        for cid, resp in zip(batch, responses):
            if isinstance(resp, BaseException):
                continue
            content = resp.get("result", {}).get("content", {})
            if content.get("mimeType"):
                results[cid] = content["mimeType"]
    return results


def _collect_leaves(node: dict) -> list[dict]:
    """Recursively collect leaf nodes (resources) from a hierarchy node."""
    children = node.get("children") or []
    if not children:
        return [node]
    leaves = []
    for child in children:
        leaves.extend(_collect_leaves(child))
    return leaves


async def get_course_outline(params: GetCourseOutlineInput) -> GetCourseOutlineOutput:
    """Tool 2: Get full course structure — units, lessons, and resource types."""
    try:
        data = await kong_get(f"/course/v1/hierarchy/{params.course_id}")
        content = data.get("result", {}).get("content", {})

        if not content:
            return GetCourseOutlineOutput(
                course_id=params.course_id,
                course_name="",
                description="Course not found.",
                total_units=0,
                units=[],
            )

        top_children: list[dict] = content.get("children") or []

        # Collect all leaf IDs missing mimeType for a single batch-fetch pass
        all_leaves: list[dict] = []
        for unit in top_children:
            all_leaves.extend(_collect_leaves(unit))

        missing_ids = [
            leaf["identifier"]
            for leaf in all_leaves
            if not leaf.get("mimeType") and leaf.get("identifier")
        ]
        mime_map = await _fetch_mime_types(missing_ids)

        # Build unit/lesson tree
        units: list[OutlineUnit] = []
        for unit in top_children:
            lessons: list[OutlineLesson] = []
            for leaf in _collect_leaves(unit):
                leaf_id = leaf.get("identifier", "")
                mime = leaf.get("mimeType") or mime_map.get(leaf_id, "")
                lessons.append(
                    OutlineLesson(
                        id=leaf_id,
                        name=leaf.get("name", ""),
                        type=leaf.get("contentType", ""),
                        mime_type=mime,
                        estimated_minutes=_duration_to_minutes(leaf.get("duration")),
                        consume_url=build_consume_url(params.course_id, params.batch_id or "", leaf_id),
                    )
                )
            units.append(
                OutlineUnit(
                    name=unit.get("name", ""),
                    lesson_count=len(lessons),
                    lessons=lessons,
                )
            )

        return GetCourseOutlineOutput(
            course_id=params.course_id,
            course_name=content.get("name", ""),
            description=content.get("description", ""),
            total_units=len(units),
            units=units,
        )

    except SunbirdApiError:
        raise
    except Exception as exc:
        raise ValueError(f"get_course_outline failed unexpectedly: {exc}") from exc
