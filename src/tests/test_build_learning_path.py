import pytest
import respx
from httpx import Response

from schemas.tool_schemas import BuildLearningPathInput
from tools.build_learning_path import build_learning_path
from config.env import env

MOCK_SEARCH_RESPONSE = {
    "id": "api.composite.search",
    "ver": "3.0",
    "params": {"resmsgid": "uuid", "status": "successful"},
    "responseCode": "OK",
    "result": {
        "count": 1,
        "content": [
            {
                "identifier": "do_123",
                "name": "Apache Flink Basics",
                "description": "Learn Flink",
                "level": "beginner",
                "language": ["English"],
            }
        ],
    },
}

MOCK_HIERARCHY_RESPONSE = {
    "id": "api.course.hierarchy",
    "ver": "3.0",
    "params": {"resmsgid": "uuid", "status": "successful"},
    "responseCode": "OK",
    "result": {
        "content": {
            "identifier": "do_123",
            "children": [
                {
                    "identifier": "unit_1",
                    "duration": 3600,
                }
            ],
        }
    },
}

MOCK_BATCH_RESPONSE = {
    "id": "api.course.batch.list",
    "ver": "1.0",
    "params": {"resmsgid": "uuid", "status": "successful"},
    "responseCode": "OK",
    "result": {
        "response": {
            "count": 1,
            "content": [{"batchId": "b1", "status": 1}],
        }
    },
}


@pytest.mark.asyncio
@respx.mock
async def test_build_learning_path_finds_courses():
    # Mock search 1 (no level)
    respx.post(f"{env.KONG_URL}/composite/v1/search").mock(
        return_value=Response(200, json=MOCK_SEARCH_RESPONSE)
    )
    
    # Mock hierarchy
    respx.get(f"{env.KONG_URL}/course/v1/hierarchy/do_123").mock(
        return_value=Response(200, json=MOCK_HIERARCHY_RESPONSE)
    )
    
    # Mock batch list
    respx.post(f"{env.KONG_URL}/course/v1/batch/list").mock(
        return_value=Response(200, json=MOCK_BATCH_RESPONSE)
    )

    # For resolve_channel_id if called during setup
    respx.post(f"{env.KONG_URL}/org/v2/search").mock(
        return_value=Response(200, json={"result": {"response": {"content": [{"hashTagId": "mock-channel"}]}}})
    )

    params = BuildLearningPathInput(
        topic="Flink",
        level="beginner",
        language="English",
        max_courses=3,
    )
    
    result = await build_learning_path(params)
    
    assert result.topic == "Flink"
    assert result.total_courses == 1
    assert len(result.path) == 1
    
    path_item = result.path[0]
    assert path_item.course_id == "do_123"
    assert path_item.name == "Apache Flink Basics"
    assert path_item.estimated_hours == 1.0
    assert path_item.unit_count == 1
    assert path_item.has_batch is True
