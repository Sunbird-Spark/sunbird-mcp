"""
Tool 5 — navigate_course

Goal-driven course navigator.
User says "I want to learn Apache Flink" — the tool extracts keywords,
finds matching courses, ranks them, fetches their outlines, and tags
each unit as relevant based on goal keywords.

Steps:
  1. Extract keywords from free-text goal (stop-word strip)
  2. POST /composite/v1/search
  3. Relevance-score + rank, take top max_results
  4. Parallel GET /course/v1/hierarchy for each top course
  5. Build goal-tagged unit outline
  6. Return courses + AI-readable suggestion string
"""
from __future__ import annotations

import asyncio
import logging
import re

from client.sunbird_client import SunbirdApiError, kong_get, kong_post

logger = logging.getLogger(__name__)
from schemas.tool_schemas import (
    CourseNavResult,
    LessonItem,
    NavigateCourseInput,
    NavigateCourseOutput,
    UnitOutline,
)


# ── keyword extraction ────────────────────────────────────────────────────────

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "i", "want", "to", "learn", "understand", "help", "me", "how",
        "do", "get", "started", "with", "about", "the", "a", "an",
        "in", "and", "or", "can", "you", "please", "study", "know",
        "basics", "fundamentals",
    }
)


def extract_query(goal: str) -> str:
    """Strip stop words from natural-language goal to derive a search query."""
    tokens = re.sub(r"[^\w\s]", "", goal.lower()).split()
    keywords = [t for t in tokens if t not in _STOP_WORDS]
    return " ".join(keywords) if keywords else goal.strip()


def extract_keywords(goal: str) -> list[str]:
    """Return individual meaningful keywords (used for relevance scoring + unit tagging)."""
    tokens = re.sub(r"[^\w\s]", "", goal.lower()).split()
    return [t for t in tokens if t not in _STOP_WORDS]


# ── helpers ───────────────────────────────────────────────────────────────────

def _relevance_score(course: dict, keywords: list[str]) -> int:
    """Score how relevant a course is to the goal keywords."""
    name = (course.get("name") or "").lower()
    desc = (course.get("description") or "").lower()
    score = 0
    for kw in keywords:
        if kw in name:
            score += 3
        elif kw in desc:
            score += 1
    return score


def _estimated_hours(hierarchy: dict) -> float:
    children = (
        hierarchy.get("result", {})
        .get("content", {})
        .get("children", [])
    )
    total_secs = sum(int(c.get("duration") or 0) for c in children)
    return round(total_secs / 3600, 1)


def _build_outline(hierarchy: dict, keywords: list[str]) -> list[UnitOutline]:
    """Walk the hierarchy tree and tag units as relevant to goal keywords."""
    children = (
        hierarchy.get("result", {})
        .get("content", {})
        .get("children", [])
    )
    units: list[UnitOutline] = []
    for unit in children:
        unit_name: str = unit.get("name") or ""
        unit_name_lc = unit_name.lower()
        relevant = any(kw in unit_name_lc for kw in keywords)

        lessons: list[LessonItem] = []
        for leaf in unit.get("children") or []:
            lessons.append(
                LessonItem(
                    id=leaf.get("identifier") or "",
                    name=leaf.get("name") or "",
                    type=leaf.get("contentType") or "",
                    mime_type=leaf.get("mimeType") or "",
                )
            )

        units.append(
            UnitOutline(
                unit_name=unit_name,
                relevant=relevant,
                lesson_count=len(lessons),
                lessons=lessons,
            )
        )
    return units


def _build_suggestion(courses: list[CourseNavResult], goal: str) -> str:
    """Generate a human-readable suggestion string for the AI to present."""
    if not courses:
        return f"No courses found for your goal: '{goal}'."

    top = courses[0]
    relevant_units = [u for u in top.outline if u.relevant]

    if relevant_units:
        unit_names = ", ".join(f"'{u.unit_name}'" for u in relevant_units[:3])
        return (
            f"Start with '{top.name}' ({top.total_units} units, ~{top.estimated_hours}h). "
            f"Units most relevant to your goal: {unit_names}."
        )
    return (
        f"Start with '{top.name}' — it has {top.total_units} units and about "
        f"{top.estimated_hours} hours of content aligned to your goal."
    )


# ── main handler ──────────────────────────────────────────────────────────────

async def navigate_course(params: NavigateCourseInput) -> NavigateCourseOutput:
    """
    Tool 5: Find courses matching user's learning goal and return a goal-tagged outline.
    """
    try:
        search_query = extract_query(params.goal)
        keywords = extract_keywords(params.goal)

        # Step 2 — search
        body = {
            "request": {
                "query": search_query,
                "filters": {
                    "status": ["Live"],
                    "contentType": ["Course", "Collection"],
                    "language": [params.language],
                },
                "limit": params.max_results * 3,
                "fields": ["identifier", "name", "description", "language"],
            }
        }
        search_data = await kong_post("/composite/v1/search", body)
        raw_courses: list[dict] = search_data.get("result", {}).get("content", []) or []

        if not raw_courses:
            return NavigateCourseOutput(
                goal=params.goal,
                search_query=search_query,
                courses_found=0,
                courses=[],
                suggestion=f"No courses found for: '{params.goal}'.",
            )

        # Step 3 — score + take top N
        scored = sorted(
            raw_courses,
            key=lambda c: _relevance_score(c, keywords),
            reverse=True,
        )[: params.max_results]

        # Step 4 — parallel hierarchy fetch; skip courses whose hierarchy call fails
        hierarchy_results: list[dict | BaseException] = await asyncio.gather(
            *[kong_get(f"/course/v1/hierarchy/{c['identifier']}") for c in scored],
            return_exceptions=True,
        )

        # Step 5 — build goal-tagged outlines, silently drop failed hierarchy fetches
        results: list[CourseNavResult] = []
        for course, hierarchy in zip(scored, hierarchy_results):
            if isinstance(hierarchy, BaseException):
                logger.warning("Hierarchy fetch failed for %s: %s", course.get("identifier"), hierarchy)
                continue
            outline = _build_outline(hierarchy, keywords)
            results.append(
                CourseNavResult(
                    course_id=course.get("identifier", ""),
                    name=course.get("name", ""),
                    description=course.get("description", ""),
                    relevance_score=_relevance_score(course, keywords),
                    total_units=len(outline),
                    estimated_hours=_estimated_hours(hierarchy),
                    outline=outline,
                )
            )

        suggestion = _build_suggestion(results, params.goal)

        return NavigateCourseOutput(
            goal=params.goal,
            search_query=search_query,
            courses_found=len(results),
            courses=results,
            suggestion=suggestion,
        )

    except SunbirdApiError:
        raise
    except Exception as exc:
        raise ValueError(f"navigate_course failed unexpectedly: {exc}") from exc
