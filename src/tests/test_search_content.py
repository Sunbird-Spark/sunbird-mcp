import pytest
import respx
from httpx import Response

from schemas.tool_schemas import SearchContentInput
from tools.search_content import search_content
from config.env import env

MOCK_SEARCH_RESPONSE = {
    "result": {
        "count": 2,
        "content": [
            {
                "identifier": "do_001",
                "name": "Intro to Flink",
                "description": "Learn Apache Flink",
                "contentType": "Course",
                "mimeType": "application/vnd.ekstep.content-collection",
                "appIcon": "https://example.com/icon.png",
                "language": ["English"],
                "framework": "NCFCOPY",
            },
            {
                "identifier": "do_002",
                "name": "Flink Advanced",
                "description": "Advanced Flink patterns",
                "contentType": "Course",
                "mimeType": "application/vnd.ekstep.content-collection",
                "appIcon": "",
                "language": ["English"],
                "framework": "",
            },
        ],
    }
}


@respx.mock
async def test_search_content_returns_results():
    respx.post(f"{env.KONG_URL}/composite/v1/search").mock(
        return_value=Response(200, json=MOCK_SEARCH_RESPONSE)
    )

    params = SearchContentInput(query="Flink", content_type="Course", language="English", limit=10)
    result = await search_content(params)

    assert result.total == 2
    assert len(result.results) == 2
    assert result.results[0].id == "do_001"
    assert result.results[0].name == "Intro to Flink"
    assert result.results[0].type == "Course"
    assert result.results[0].language == "English"
    assert result.message is None


@respx.mock
async def test_search_content_empty_results():
    respx.post(f"{env.KONG_URL}/composite/v1/search").mock(
        return_value=Response(200, json={"result": {"count": 0, "content": []}})
    )

    params = SearchContentInput(query="nonexistent-xyz-abc")
    result = await search_content(params)

    assert result.total == 0
    assert result.results == []
    assert result.message is not None
    assert "nonexistent-xyz-abc" in result.message
