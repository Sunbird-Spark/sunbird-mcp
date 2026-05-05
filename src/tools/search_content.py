"""
Tool 1 — search_content

Full-text search for courses, resources, and question sets.

Steps:
  1. POST /composite/v1/search with query + optional contentType/language filters
  2. Map results to clean output shape
"""
from __future__ import annotations

from client.sunbird_client import SunbirdApiError, kong_post
from schemas.tool_schemas import (
    SearchContentInput,
    SearchContentOutput,
    SearchResultItem,
)


async def search_content(params: SearchContentInput) -> SearchContentOutput:
    """Tool 1: Search Sunbird for courses, resources, or question sets by keyword."""
    try:
        filters: dict = {"status": ["Live"]}
        if params.content_type:
            filters["contentType"] = [params.content_type]
        if params.language:
            filters["language"] = [params.language]

        body = {
            "request": {
                "query": params.query,
                "filters": filters,
                "limit": params.limit,
                "fields": [
                    "identifier",
                    "name",
                    "description",
                    "contentType",
                    "mimeType",
                    "appIcon",
                    "language",
                    "framework",
                    "primaryCategory",
                ],
            }
        }

        data = await kong_post("/composite/v1/search", body)
        result = data.get("result", {})
        count: int = result.get("count", 0)
        raw: list[dict] = result.get("content", []) or []

        if count == 0 or not raw:
            return SearchContentOutput(
                total=0,
                results=[],
                message=f"No content found for query: '{params.query}'.",
            )

        items: list[SearchResultItem] = []
        for c in raw:
            lang = c.get("language") or []
            items.append(
                SearchResultItem(
                    id=c.get("identifier", ""),
                    name=c.get("name", ""),
                    description=c.get("description", ""),
                    type=c.get("contentType", "") or c.get("primaryCategory", ""),
                    mime_type=c.get("mimeType", ""),
                    thumbnail_url=c.get("appIcon", ""),
                    language=lang[0] if lang else "",
                    framework=c.get("framework", ""),
                )
            )

        return SearchContentOutput(total=count, results=items)

    except SunbirdApiError:
        raise
    except Exception as exc:
        raise ValueError(f"search_content failed unexpectedly: {exc}") from exc
