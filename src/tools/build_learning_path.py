"""
Tool 4 — build_learning_path

Builds an ordered, scored list of courses for a given topic/skill.

Steps:
  1. Single composite search (level is NOT sent as an API filter — Sunbird's
     `level` field is numeric in ES and rejects string values with a 500)
  2. Deduplicate + score results (level used only in scoring, not filtering)
  3. Parallel enrichment: course hierarchy + batch list per course
     (return_exceptions=True so one 404/500 doesn't kill the whole path)
  4. Return ordered path with estimated hours and batch availability
"""
from __future__ import annotations

import asyncio
import logging

from client.sunbird_client import SunbirdApiError, kong_get, kong_post
from schemas.tool_schemas import (
    BuildLearningPathInput,
    BuildLearningPathOutput,
    CoursePathItem,
)

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _search_courses(query: str, language: str, limit: int = 20) -> list[dict]:
    """Composite search for live courses matching query."""
    body = {
        "request": {
            "query": query,
            "filters": {
                "status": ["Live"],
                "contentType": ["Course"],
                "language": [language],
            },
            "limit": limit,
            "fields": ["identifier", "name", "description", "level", "language"],
        }
    }
    data = await kong_post("/composite/v1/search", body)
    return data.get("result", {}).get("content", []) or []


def _score_course(course: dict, topic: str, level: str | None, language: str) -> int:
    """Score course relevance. Higher is more relevant."""
    score = 0
    name = (course.get("name") or "").lower()
    desc = (course.get("description") or "").lower()
    topic_lc = topic.lower()

    if topic_lc in name:
        score += 3
    elif topic_lc in desc:
        score += 1

    if level:
        course_level = (course.get("level") or "").lower()
        if level.lower() in course_level:
            score += 2

    course_languages = [lang.lower() for lang in (course.get("language") or [])]
    if language.lower() in course_languages:
        score += 1

    return score


def _estimated_hours(hierarchy: dict) -> float:
    """Derive estimated hours from unit-level duration fields."""
    children = (
        hierarchy.get("result", {})
        .get("content", {})
        .get("children", [])
    )
    total_secs = sum(int(c.get("duration") or 0) for c in children)
    return round(total_secs / 3600, 1)


async def _enrich_course(course_id: str) -> tuple[dict, dict]:
    """Fetch hierarchy + batch list for a course in parallel."""
    hierarchy, batches = await asyncio.gather(
        kong_get(f"/course/v1/hierarchy/{course_id}"),
        kong_post(
            "/course/v1/batch/list",
            {"request": {"filters": {"courseId": course_id, "status": ["1", "0"]}}},
        ),
    )
    return hierarchy, batches


# ── main handler ──────────────────────────────────────────────────────────────

async def build_learning_path(params: BuildLearningPathInput) -> BuildLearningPathOutput:
    """
    Tool 4: Curate an ordered set of courses for a topic/skill.
    Returns a scored, enriched learning path with batch availability.
    """
    try:
        # Phase 1 — search (no level filter: Sunbird ES rejects string values)
        raw_courses = await _search_courses(params.topic, params.language)

        if not raw_courses:
            return BuildLearningPathOutput(
                topic=params.topic,
                total_courses=0,
                path=[],
                summary=f"No courses found for '{params.topic}'.",
            )

        # Phase 2 — deduplicate, score by level/language in response data, take top N
        seen: dict[str, dict] = {}
        for course in raw_courses:
            cid = course.get("identifier", "")
            if cid:
                seen[cid] = course

        scored = sorted(
            seen.values(),
            key=lambda c: _score_course(c, params.topic, params.level, params.language),
            reverse=True,
        )[: params.max_courses]

        # Phase 3 — parallel enrichment; skip any course whose hierarchy/batch call fails
        enrichment_results: list[tuple[dict, dict] | BaseException] = await asyncio.gather(
            *[_enrich_course(c["identifier"]) for c in scored],
            return_exceptions=True,
        )

        # Phase 4 — build output, silently skip enrichment failures
        path: list[CoursePathItem] = []
        for i, (course, enrichment) in enumerate(zip(scored, enrichment_results), start=1):
            if isinstance(enrichment, BaseException):
                logger.warning("Enrichment failed for %s: %s", course.get("identifier"), enrichment)
                hierarchy, batches = {}, {}
            else:
                hierarchy, batches = enrichment

            children = (
                hierarchy.get("result", {}).get("content", {}).get("children", [])
            )
            batch_list = (
                batches.get("result", {}).get("response", {}).get("content", [])
            ) or []

            level_label = f" at {params.level} level" if params.level else ""
            path.append(
                CoursePathItem(
                    order=i,
                    course_id=course["identifier"],
                    name=course.get("name", ""),
                    why=f"Covers {params.topic}{level_label}",
                    estimated_hours=_estimated_hours(hierarchy),
                    unit_count=len(children),
                    has_batch=len(batch_list) > 0,
                )
            )

        level_str = f" ({params.level})" if params.level else ""
        summary = f"A {len(path)}-course path covering {params.topic}{level_str} in {params.language}."

        return BuildLearningPathOutput(
            topic=params.topic,
            total_courses=len(path),
            path=path,
            summary=summary,
        )

    except SunbirdApiError:
        raise
    except Exception as exc:
        raise ValueError(f"build_learning_path failed unexpectedly: {exc}") from exc
