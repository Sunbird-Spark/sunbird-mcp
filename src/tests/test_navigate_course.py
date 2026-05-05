import pytest
import respx
from httpx import Response

from schemas.tool_schemas import NavigateCourseInput
from tools.navigate_course import navigate_course, extract_query, extract_keywords
from config.env import env


def test_keyword_extraction():
    goal = "I want to learn Apache Flink for stream processing"
    query = extract_query(goal)
    keywords = extract_keywords(goal)
    
    assert query == "apache flink for stream processing"
    assert "apache" in keywords
    assert "flink" in keywords


MOCK_SEARCH_RESPONSE = {
    "result": {
        "content": [
            {
                "identifier": "do_123",
                "name": "Big Data with Flink",
                "description": "Learn stream processing",
                "language": ["English"],
            }
        ]
    }
}

MOCK_HIERARCHY_RESPONSE = {
    "result": {
        "content": {
            "children": [
                {
                    "name": "Unit 1: Flink Architecture",
                    "children": [
                        {"identifier": "l1", "name": "Lesson 1", "contentType": "Video", "duration": 1800}
                    ],
                    "duration": 1800
                },
                {
                    "name": "Unit 2: Unrelated stuff",
                    "children": [],
                    "duration": 1800
                }
            ]
        }
    }
}


@pytest.mark.asyncio
@respx.mock
async def test_navigate_course():
    # Mock search
    respx.post(f"{env.KONG_URL}/composite/v1/search").mock(
        return_value=Response(200, json=MOCK_SEARCH_RESPONSE)
    )
    
    # Mock hierarchy
    respx.get(f"{env.KONG_URL}/course/v1/hierarchy/do_123").mock(
        return_value=Response(200, json=MOCK_HIERARCHY_RESPONSE)
    )

    params = NavigateCourseInput(
        goal="I want to learn Flink",
        language="English",
        max_results=3,
    )
    
    result = await navigate_course(params)
    
    assert result.goal == "I want to learn Flink"
    assert result.courses_found == 1
    
    course = result.courses[0]
    assert course.course_id == "do_123"
    assert course.estimated_hours == 1.0  # 3600 seconds total
    
    # Check outline tagging
    assert len(course.outline) == 2
    # "flink architecture" contains "flink" -> relevant
    assert course.outline[0].relevant is True
    # "unrelated stuff" -> not relevant
    assert course.outline[1].relevant is False
